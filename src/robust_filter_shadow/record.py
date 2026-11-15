"""Build one board both ways and extract its shadow record.

The incumbent and the challenger are two builds of the SAME inputs through the
canonical pipeline (``value_replay.build``), differing only in the challenger's
flag. Two challengers are registered (:data:`CHALLENGERS`), each with its own
preregistration and its own ledger directory:

* ``joint`` (the default) -- ``joint_outlier_sparse_challenger``. The sparse half
  (``joint_sparse_limited_evidence``) is pinned OFF in both builds, so the record
  isolates the filter half -- the owner requirement that the halves stay
  separate.
* ``rank_space`` -- ``rank_space_hampel_challenger`` (``rank-space-hampel-v1``).
  Both builds pin the joint filter and its sparse half OFF; only the
  rank-space flag differs.
* ``rank_space_per_vote`` -- ``rank_space_hampel_per_vote_challenger``
  (``rank-space-hampel-per-vote-v1``, a separate follow-up experiment). Both
  builds pin the joint filter, its sparse half and ``rank_space_hampel_challenger``
  OFF; only the per-vote flag differs.

Everything recorded is read from what the pipeline itself stamped
(``sourceRankMeta``, ``droppedSources``, ``jointFilterReasons``,
``rankDerivedValue``, ``canonicalConsensusRank``). The two filters are re-run
here only to CHECK that the stamped decisions are reproducible from the stamped
inputs, and to report each filter's centre / scale / threshold.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from src.api import data_contract as dc
from src.api.joint_robust_filter import CHALLENGER_VERSION, joint_robust_filter

SCHEMA = "joint-filter-shadow/v1"
CHALLENGER_FLAG = "joint_outlier_sparse_challenger"
SPARSE_FLAG = "joint_sparse_limited_evidence"
RANK_SPACE_FLAG = "rank_space_hampel_challenger"
RANK_SPACE_VERSION = "rank-space-hampel-v1"
PER_VOTE_FLAG = "rank_space_hampel_per_vote_challenger"
PER_VOTE_VERSION = "rank-space-hampel-per-vote-v1"
CHALLENGER_JOINT = "joint"
CHALLENGER_RANK_SPACE = "rank_space"
CHALLENGER_PER_VOTE = "rank_space_per_vote"
#: Challengers whose records carry the rank-space F1 diagnostics table.
RANK_SPACE_KINDS = (CHALLENGER_RANK_SPACE, CHALLENGER_PER_VOTE)
#: One entry per registered challenger: the flags each build pins, the version
#: stamped in ``pins.challengerVersion`` (and so in the record key), the
#: preregistration that fixes its evaluation, and its bootstrap seed.
#: ``joint`` is byte-identical to the single-challenger recorder it generalises.
CHALLENGERS: dict[str, dict[str, Any]] = {
    CHALLENGER_JOINT: {
        "version": CHALLENGER_VERSION,
        "incumbent": [(CHALLENGER_FLAG, False), (SPARSE_FLAG, False)],
        "challenger": [(CHALLENGER_FLAG, True), (SPARSE_FLAG, False)],
        "preregistration": (
            "docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md"
        ),
        "bootstrapSeed": 1571,
    },
    CHALLENGER_RANK_SPACE: {
        "version": RANK_SPACE_VERSION,
        "incumbent": [(CHALLENGER_FLAG, False), (SPARSE_FLAG, False), (RANK_SPACE_FLAG, False)],
        "challenger": [(CHALLENGER_FLAG, False), (SPARSE_FLAG, False), (RANK_SPACE_FLAG, True)],
        "preregistration": (
            "docs/valuation/evidence/rank-space-hampel-2026-10-17/PREREGISTRATION.md"
        ),
        # rank-space PREREGISTRATION §2: seed 17, so the two evaluations are
        # never mistaken for one another.
        "bootstrapSeed": 17,
    },
    CHALLENGER_PER_VOTE: {
        "version": PER_VOTE_VERSION,
        "incumbent": [
            (CHALLENGER_FLAG, False),
            (SPARSE_FLAG, False),
            (RANK_SPACE_FLAG, False),
            (PER_VOTE_FLAG, False),
        ],
        "challenger": [
            (CHALLENGER_FLAG, False),
            (SPARSE_FLAG, False),
            (RANK_SPACE_FLAG, False),
            (PER_VOTE_FLAG, True),
        ],
        "preregistration": (
            "docs/valuation/evidence/rank-space-hampel-per-vote-2026-10-17/PREREGISTRATION.md"
        ),
        # per-vote PREREGISTRATION §2: seed 2027 (neither 1571 nor 17).
        "bootstrapSeed": 2027,
    },
}


def challenger_spec(challenger: str = CHALLENGER_JOINT) -> dict[str, Any]:
    """The registry entry for ``challenger`` (``KeyError`` names an unknown one)."""
    try:
        return CHALLENGERS[challenger]
    except KeyError:
        raise KeyError(f"unknown challenger {challenger!r}; known: {sorted(CHALLENGERS)}") from None


MODE_REPLAY = "historical_replay"
MODE_LIVE = "live_shadow"
LABELS = {
    MODE_REPLAY: (
        "archived inputs rebuilt through today's pipeline code -- NOT what "
        "production served that day"
    ),
    MODE_LIVE: (
        "live shadow: this box's production inputs at record time, built through "
        "the deployed code with only the challenger flag changed"
    ),
}
CHURN_DEPTHS = (50, 100, 200, 400)
SAFEGUARD_REASONS = ("dominant_evidence_kept", "kept_to_avoid_single_family")
#: Files whose content decides the board-scale votes the evaluation compares
#: across boards. Two records with different fingerprints were built by
#: different value code / curves, so their votes are not on one scale.
#:
#: Widened 2026-10-01 (PR #1590 review): the first version covered only the
#: first four entries and missed the TE basis conversion, the tail policy, the
#: rank-coordinate / IDP-backbone translation, the freshness and dataset-state
#: owners and the weight configs -- all of which shape a vote or its weight.
#: Records written before the widening carry the narrower fingerprint and so
#: never pair with records written after it.
FINGERPRINT_FILES = (
    "src/api/data_contract.py",
    "src/api/joint_robust_filter.py",
    "src/canonical/player_valuation.py",
    "config/sources/freshness_v1.json",
    "src/league_intel/te_premium.py",
    "src/canonical/tail_policy.py",
    "src/canonical/rank_coordinates.py",
    "src/canonical/idp_backbone.py",
    "src/sources/freshness.py",
    "src/sources/dataset_state.py",
)
#: Every file matching these joins the fingerprint too, so a weight config
#: added later is covered without editing this list.
FINGERPRINT_GLOBS = ("config/weights/*.json",)


def variant_specs(
    csv_root: Path | str | None = None, challenger: str = CHALLENGER_JOINT
) -> tuple[dict, dict]:
    """``(incumbent_spec, challenger_spec)`` for ``value_replay.build``."""
    spec = challenger_spec(challenger)
    base: dict[str, Any] = {"csv_root": Path(csv_root)} if csv_root is not None else {}
    incumbent = {**base, "flags": list(spec["incumbent"])}
    challenger_build = {**base, "flags": list(spec["challenger"])}
    return incumbent, challenger_build


def variant_flags(challenger: str = CHALLENGER_JOINT) -> dict[str, dict[str, bool]]:
    """``{"incumbent": {flag: on}, "challenger": {flag: on}}`` -- the pinned variants."""
    spec = challenger_spec(challenger)
    return {
        "incumbent": dict(spec["incumbent"]),
        "challenger": dict(spec["challenger"]),
    }


def build_pair(
    raw_payload: Mapping[str, Any],
    csv_root: Path | str | None = None,
    challenger: str = CHALLENGER_JOINT,
) -> tuple[dict, dict]:
    """The incumbent and challenger contracts for one raw payload."""
    from src.api import value_replay as vr  # noqa: PLC0415 -- heavy import, CLI-time only

    inc_spec, ch_spec = variant_specs(csv_root, challenger)
    return vr.build(raw_payload, inc_spec), vr.build(raw_payload, ch_spec)


def voting_observations(row: Mapping[str, Any]) -> dict[str, float]:
    """``{source: board-scale vote}`` for every observation that voted.

    The vote is the stamped ``valueContribution`` -- computed BEFORE the outlier
    filter, so it is the same number in both builds. An observation with an
    ``excludedReason`` (zero freshness/health weight) did not vote and is not an
    observation either filter judged.
    """
    meta = row.get("sourceRankMeta") or {}
    out: dict[str, float] = {}
    for source, m in meta.items():
        if not isinstance(m, Mapping) or m.get("excludedReason"):
            continue
        value = m.get("valueContribution")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            out[str(source)] = float(value)
    return out


def precap_weight(meta: Mapping[str, Any]) -> float:
    """The observation's effective weight before the family cap.

    ``appliedWeight`` is overwritten with the capped weight on survivors whose
    family was capped (``preFamilyWeight`` keeps the original); an observation
    the incumbent dropped never reaches the cap and keeps its pre-cap weight.
    """
    raw = meta.get("preFamilyWeight", meta.get("appliedWeight", 1.0))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def is_filter_row(row: Mapping[str, Any], observations: Mapping[str, float]) -> bool:
    """Rows the per-player filter runs on: non-pick, at least ``_HAMPEL_MIN_N`` votes."""
    return row.get("assetClass") != "pick" and len(observations) >= dc._HAMPEL_MIN_N


def incumbent_statistics(values: Iterable[float]) -> dict[str, float]:
    """Median, median absolute deviation and threshold of the incumbent filter."""
    vals = list(values)
    centre = statistics.median(vals)
    mad = statistics.median(abs(v - centre) for v in vals)
    return {
        "centre": round(centre, 2),
        "scale": round(mad, 2),
        "threshold": round(max(dc._HAMPEL_K * mad, dc._HAMPEL_MIN_THRESHOLD), 2),
    }


def challenger_weights(
    observations: Mapping[str, float], meta: Mapping[str, Any]
) -> tuple[dict[str, float], dict[str, float]]:
    """``(pre_cap, capped)`` evidence weights, exactly as the challenger sees them.

    Capping uses ``cap_family_weights`` with the registry base weights (all 1.0
    by policy, so the cap is one provider's authority). A user weight override
    would change the base; shadow builds carry none.
    """
    pre = {s: precap_weight(meta.get(s) or {}) for s in observations}
    capped, _factors = dc.cap_family_weights(pre)
    return pre, capped


def rank_space_curve(row: Mapping[str, Any]) -> tuple[float, float]:
    """The scope master Hill curve the rank-space challenger reads for ``row``.

    The same selection ``data_contract._compute_unified_rankings`` makes: IDP
    rows read the IDP master, every other row the OFFENSE master.
    """
    from src.canonical import player_valuation as pv  # noqa: PLC0415

    if row.get("assetClass") == "idp":
        return (pv.IDP_HILL_PERCENTILE_C, pv.IDP_HILL_PERCENTILE_S)
    return (pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S)


def rank_space_statistics(
    values: Iterable[float], curve: tuple[float, float]
) -> dict[str, float | None]:
    """Median, MAD and threshold of the rank-space filter, in percentile units.

    Reporting only (the decision is ``dc._hampel_filter_rank_space``'s own);
    the floor is the incumbent's ``_HAMPEL_MIN_THRESHOLD`` carried into
    percentile space at the median, as the preregistration defines it.
    """
    import math  # noqa: PLC0415

    c, s = curve
    coords = [dc._hill_inverse(float(v), c, s) for v in values]
    finite = [u for u in coords if math.isfinite(u)]
    if not finite:
        return {"centre": None, "scale": None, "threshold": None}
    centre = statistics.median(finite)
    mad = statistics.median(abs(u - centre) for u in finite)
    v_med = 9999.0 / (1.0 + (centre / c) ** s) if centre > 0 else 9999.0
    hi = dc._hill_inverse(max(1.0, v_med - dc._HAMPEL_MIN_THRESHOLD / 2.0), c, s)
    lo = dc._hill_inverse(min(9999.0, v_med + dc._HAMPEL_MIN_THRESHOLD / 2.0), c, s)
    floor_u = abs(hi - lo) if math.isfinite(hi) else math.inf
    threshold = max(dc._HAMPEL_K * mad, floor_u)
    return {
        "centre": round(centre, 6),
        "scale": round(mad, 6),
        "threshold": None if not math.isfinite(threshold) else round(threshold, 6),
    }


def per_vote_forward_maps(row: Mapping[str, Any]) -> dict[str, tuple]:
    """``{source: (c, s, te_kind, te_param)}`` rebuilt from the row's STAMPS.

    For the reproduction check only (the decision itself uses the maps the blend
    loop recorded while pricing). The curve is the stamped
    ``rankCoordinatePool`` (else the source's native pool -- the pipeline's own
    fallback); the TE transform is read from ``tepBasisFrom``/``tepBasisTo``,
    ``tepMultiplier`` or ``tepNativeCorrection``.
    """
    from src.canonical.rank_coordinates import (  # noqa: PLC0415
        curve_for_pool,
        native_pool_for_source,
    )

    registry = {str(s.get("key")): s for s in dc._RANKING_SOURCES}
    out: dict[str, tuple] = {}
    for source, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, Mapping):
            continue
        pool = str(m.get("rankCoordinatePool") or "") or native_pool_for_source(
            registry.get(str(source), {})
        )
        c, s = curve_for_pool(pool)
        kind: str | None = None
        param: Any = None
        if m.get("tepBoostApplied"):
            if m.get("tepBasisFrom") and m.get("tepBasisTo"):
                kind, param = dc.PER_VOTE_TE_BASIS, (m["tepBasisFrom"], m["tepBasisTo"])
            else:
                kind, param = dc.PER_VOTE_TE_FLAT, float(m.get("tepMultiplier"))
        elif m.get("tepNativeCorrectionApplied"):
            kind, param = dc.PER_VOTE_TE_FLAT, float(m.get("tepNativeCorrection"))
        out[str(source)] = (c, s, kind, param)
    return out


def curve_family(forward_map: tuple, source: str, meta: Mapping[str, Any]) -> str:
    """Census label: curve (GLOBAL/OFFENSE/IDP), plus ``+te`` and ``+value_direct``."""
    from src.canonical import rank_coordinates as rc  # noqa: PLC0415

    c, s = forward_map[0], forward_map[1]
    label = next(
        (rc.curve_label_for_pool(pool) for pool, cs in rc._CURVE_BY_POOL.items() if cs == (c, s)),
        "UNKNOWN",
    )
    if forward_map[2] is not None:
        label += "+te"
    if meta.get("valueContributionPath") == "value_direct":
        label += "+value_direct"
    return label


def per_vote_statistics(
    observations: Mapping[str, float], forward_maps: Mapping[str, tuple]
) -> dict[str, Any]:
    """Median, MAD and each vote's coordinate / threshold (percentile units)."""
    import math  # noqa: PLC0415

    res = dc.rank_space_per_vote_assessment(sorted(observations.items()), forward_maps)

    def r(x: float | None) -> float | None:
        return None if x is None or not math.isfinite(x) else round(x, 6)

    return {
        "centre": r(res["median"]),
        "scale": r(res["mad"]),
        "perVote": {
            s: [r(res["coords"].get(s)), r((res["thresholds"] or {}).get(s))]
            for s in sorted(observations)
        },
        "dropped": sorted(res["dropped"]),
    }


def coordinate_census(
    incumbent: Mapping[str, Any], challenger: Mapping[str, Any]
) -> dict[str, Any]:
    """Preregistration §3 D6: votes and drops per curve family; mixed-curve rows."""
    ch_rows = {str(r.get("displayName")): r for r in challenger.get("playersArray") or []}
    fam: dict[str, Counter[str]] = {}
    rows = Counter()
    for row in incumbent.get("playersArray") or []:
        obs = voting_observations(row)
        if not is_filter_row(row, obs):
            continue
        other = ch_rows.get(str(row.get("displayName"))) or {}
        maps = per_vote_forward_maps(row)
        meta = row.get("sourceRankMeta") or {}
        inc_drop = set(row.get("droppedSources") or [])
        ch_drop = set(other.get("droppedSources") or [])
        curves = set()
        for s in obs:
            if s not in maps:
                continue
            label = curve_family(maps[s], s, meta.get(s) or {})
            curves.add(maps[s][:2])
            cell = fam.setdefault(label, Counter())
            cell["votes"] += 1
            cell["droppedIncumbent"] += s in inc_drop
            cell["droppedChallenger"] += s in ch_drop
        rows["filterRows"] += 1
        rows["mixedCurveRows"] += len(curves) > 1
    return {"byFamily": {k: dict(v) for k, v in sorted(fam.items())}, "rows": dict(rows)}


#: Rows the per-vote preregistration §3 names for a full diagnostic. Diagnostic
#: only: nothing is tuned toward any player's valuation.
DIAGNOSTIC_PLAYERS = ("Puka Nacua",)


def diagnostic_rows(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    names: Iterable[str] = DIAGNOSTIC_PLAYERS,
) -> dict[str, Any]:
    """Every vote of each named row with its curve, TE transform, coordinate,
    threshold and both filters' verdicts, plus both published values."""
    wanted = set(names)
    ch_rows = {str(r.get("displayName")): r for r in challenger.get("playersArray") or []}
    out: dict[str, Any] = {}
    for row in incumbent.get("playersArray") or []:
        name = str(row.get("displayName"))
        if name not in wanted or name in out:
            continue
        other = ch_rows.get(name) or {}
        obs = voting_observations(row)
        maps = per_vote_forward_maps(row)
        meta = row.get("sourceRankMeta") or {}
        stats = per_vote_statistics(obs, maps)
        inc_drop = set(row.get("droppedSources") or [])
        ch_drop = set(other.get("droppedSources") or [])
        market = row.get("ktcMarket") if isinstance(row.get("ktcMarket"), Mapping) else {}
        out[name] = {
            "position": row.get("position"),
            "valueIncumbent": _value(row),
            "valueChallenger": _value(other),
            "rankIncumbent": _rank(row),
            "rankChallenger": _rank(other),
            "ktcMarketNormalized": market.get("normalizedValue"),
            "incumbentStats": incumbent_statistics(obs.values()) if obs else None,
            "challengerStats": {k: stats[k] for k in ("centre", "scale")},
            "votes": [
                {
                    "source": s,
                    "value": round(v, 1),
                    "curve": curve_family(maps[s], s, meta.get(s) or {}) if s in maps else None,
                    "teTransform": list(maps[s][2:]) if s in maps else None,
                    "u": stats["perVote"].get(s, [None, None])[0],
                    "threshold": stats["perVote"].get(s, [None, None])[1],
                    "incumbent": "drop" if s in inc_drop else "keep",
                    "challenger": "drop" if s in ch_drop else "keep",
                }
                for s, v in sorted(obs.items())
            ],
        }
    return out


def row_positions(contract: Mapping[str, Any]) -> dict[str, str | None]:
    """``{name: position}`` for every non-pick row (segment reports)."""
    return {
        str(r.get("displayName")): r.get("position")
        for r in contract.get("playersArray") or []
        if r.get("assetClass") != "pick"
    }


def _rank(row: Mapping[str, Any] | None) -> int | None:
    value = (row or {}).get("canonicalConsensusRank")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _value(row: Mapping[str, Any] | None) -> float | None:
    value = (row or {}).get("rankDerivedValue")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _top(rows: Mapping[str, Mapping[str, Any]], depth: int) -> set[str]:
    return {name for name, row in rows.items() if (_rank(row) or 10**9) <= depth}


def shadow_record(
    incumbent: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    family_of: Callable[[str], str] = dc.correlation_group_for,
    challenger_kind: str = CHALLENGER_JOINT,
) -> dict[str, Any]:
    """Per-board comparison of the two filters (no board identity or pins).

    ``challenger_kind`` selects which filter the reproduction check re-runs for the
    challenger side (the joint filter, or the rank-space Hampel filter).

    ``rows`` holds every row where the filters' drop sets differ, a safeguard
    fired, or the published value moved; each carries every observation on that
    row with its family, vote, weights and both filters' verdicts.
    """
    inc_rows: dict[str, Mapping[str, Any]] = {}
    collisions = 0
    for row in incumbent.get("playersArray") or []:
        name = str(row.get("displayName"))
        collisions += name in inc_rows
        inc_rows[name] = row
    ch_rows = {str(r.get("displayName")): r for r in challenger.get("playersArray") or []}

    counts: Counter[str] = Counter()
    safeguards: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    rows_out: list[dict[str, Any]] = []
    agreed: list[list[Any]] = []
    for name in sorted(inc_rows):
        inc_row, ch_row = inc_rows[name], ch_rows.get(name)
        if ch_row is None:
            counts["rowsMissingInChallenger"] += 1
            continue
        counts["rows"] += 1
        observations = voting_observations(inc_row)
        filter_row = is_filter_row(inc_row, observations)
        inc_drop = set(inc_row.get("droppedSources") or [])
        ch_drop = set(ch_row.get("droppedSources") or [])
        reasons = dict(ch_row.get("jointFilterReasons") or {})
        fired = {s: r for s, r in reasons.items() if r in SAFEGUARD_REASONS}
        safeguards.update(fired.values())
        vi, vc = _value(inc_row), _value(ch_row)
        moved = vi is not None and vc is not None and vi != vc
        if filter_row:
            counts["filterRows"] += 1
            counts["incumbentDrops"] += len(inc_drop)
            counts["challengerDrops"] += len(ch_drop)
        if moved:
            counts["rowsValueChanged"] += 1
        if inc_drop == ch_drop and not fired and not moved:
            if filter_row and inc_drop:
                agreed.extend([name, s, inc_row.get("assetClass")] for s in sorted(inc_drop))
            continue
        if inc_drop != ch_drop:
            counts["rowsDisagree"] += 1
            counts["obsIncumbentOnlyDrop"] += len(inc_drop - ch_drop)
            counts["obsChallengerOnlyDrop"] += len(ch_drop - inc_drop)
            by_class[str(inc_row.get("assetClass"))] += 1
        meta = inc_row.get("sourceRankMeta") or {}
        pre, capped = challenger_weights(observations, meta)
        entry: dict[str, Any] = {
            "name": name,
            "assetClass": inc_row.get("assetClass"),
            "position": inc_row.get("position"),
            "valueIncumbent": vi,
            "valueChallenger": vc,
            "rankIncumbent": _rank(inc_row),
            "rankChallenger": _rank(ch_row),
            "filterRow": filter_row,
            "obs": [
                {
                    "source": s,
                    "family": family_of(s),
                    "value": int(round(v)),
                    "weight": round(pre[s], 4),
                    "weightCapped": round(capped[s], 4),
                    "freshness": (meta.get(s) or {}).get("freshness"),
                    "incumbent": "drop" if s in inc_drop else "keep",
                    "challenger": "drop" if s in ch_drop else "keep",
                    "reason": reasons.get(s),
                }
                for s, v in sorted(observations.items())
            ],
        }
        if filter_row:
            entry["incumbentStats"] = incumbent_statistics(observations.values())
            if challenger_kind == CHALLENGER_PER_VOTE:
                stats = per_vote_statistics(observations, per_vote_forward_maps(inc_row))
                ch_check = set(stats["dropped"])
                entry["challengerStats"] = stats
            elif challenger_kind == CHALLENGER_RANK_SPACE:
                curve = rank_space_curve(inc_row)
                _ch_kept, ch_dropped = dc._hampel_filter_rank_space(
                    sorted(observations.items()), curve=curve, k=dc._HAMPEL_K
                )
                ch_check = set(ch_dropped)
                entry["challengerStats"] = rank_space_statistics(observations.values(), curve)
            else:
                check = joint_robust_filter(
                    sorted(observations.items()),
                    capped,
                    {s: family_of(s) for s in observations},
                    k=dc._HAMPEL_K,
                    min_n=dc._HAMPEL_MIN_N,
                    min_threshold=dc._HAMPEL_MIN_THRESHOLD,
                )
                ch_check = set(check.dropped)
                entry["challengerStats"] = {
                    "centre": None if check.centre is None else round(check.centre, 2),
                    "scale": None if check.scale is None else round(check.scale, 2),
                    "threshold": None if check.threshold is None else round(check.threshold, 2),
                }
            _kept, inc_check = dc._hampel_filter_per_player(sorted(observations.items()))
            entry["reproduced"] = {
                "incumbent": set(inc_check) == inc_drop,
                "challenger": ch_check == ch_drop,
            }
            counts["reproducedIncumbent"] += set(inc_check) == inc_drop
            counts["reproducedChallenger"] += ch_check == ch_drop
            counts["reproductionChecked"] += 1
        rows_out.append(entry)

    churn = {
        str(depth): len(_top(inc_rows, depth) - _top(ch_rows, depth)) for depth in CHURN_DEPTHS
    }
    return {
        "counts": {**dict(sorted(counts.items())), "nameCollisions": collisions},
        "safeguardsFired": {r: safeguards.get(r, 0) for r in SAFEGUARD_REASONS},
        "disagreeRowsByAssetClass": dict(sorted(by_class.items())),
        "topChurn": churn,
        "rows": rows_out,
        # [name, source, assetClass] the two filters both dropped, on rows not
        # listed in ``rows`` (agreed outliers -- context for the evaluation).
        "agreedDrops": agreed,
    }


def observation_panel(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Every non-pick row's pre-filter votes -- what later boards are scored by.

    Compact on purpose (it is stored per board): ``{"rows": {name: {"c": asset
    class, "o": {source: vote}}}}``. Votes are pre-filter, so the incumbent and
    challenger builds produce the same panel.
    """
    rows: dict[str, Any] = {}
    for row in contract.get("playersArray") or []:
        if row.get("assetClass") == "pick":
            continue
        obs = voting_observations(row)
        if obs:
            rows[str(row.get("displayName"))] = {
                "c": row.get("assetClass"),
                "o": {s: int(round(v)) for s, v in sorted(obs.items())},
            }
    return {"schema": f"{SCHEMA}/panel", "rows": rows}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path, relative_dirs: Iterable[str], pattern: str = "*") -> str | None:
    """Content identity of the files under ``root/<dir>`` (``None`` when absent)."""
    digest = hashlib.sha256()
    found = False
    for rel in relative_dirs:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(p for p in base.glob(pattern) if p.is_file()):
            found = True
            digest.update(f"{rel}/{path.name}\0{file_sha256(path)}\n".encode())
    return digest.hexdigest() if found else None


def fingerprint_paths(repo_root: Path) -> list[str]:
    """Repo-relative paths the fingerprint covers: the fixed list, then each glob."""
    rels = list(FINGERPRINT_FILES)
    for pattern in FINGERPRINT_GLOBS:
        matched = sorted(
            p.relative_to(repo_root).as_posix() for p in repo_root.glob(pattern) if p.is_file()
        )
        rels.extend(r for r in matched if r not in rels)
    return rels


def pipeline_fingerprint(repo_root: Path) -> str:
    """sha256 over :func:`fingerprint_paths` -- which value code produced the votes."""
    digest = hashlib.sha256()
    for rel in fingerprint_paths(repo_root):
        path = repo_root / rel
        digest.update(f"{rel}\0{file_sha256(path) if path.exists() else 'missing'}\n".encode())
    return digest.hexdigest()


#: Pins that, with the payload hash, identify a panel's inputs. A panel is the
#: pre-filter votes of one build, so it is a function of the payload, the value
#: code (revision + fingerprint) and the CSV / dataset-state trees the build
#: read. All of them are in the record key as well: differing inputs are
#: distinct panels, never a conflict.
PANEL_IDENTITY_PINS = (
    "codeRevision",
    "pipelineFingerprint",
    "csvTreeSha256",
    "stateTreeSha256",
)


def panel_identity(board: Mapping[str, Any], pins: Mapping[str, Any]) -> dict[str, str]:
    """The full input identity of one board's observation panel."""
    return {
        "payloadSha256": str(board.get("payloadSha256")),
        **{k: str(pins.get(k)) for k in PANEL_IDENTITY_PINS},
    }


def record_key(record: Mapping[str, Any]) -> str:
    """Idempotency key: one record per (mode, board inputs, code, challenger)."""
    pins = record.get("pins") or {}
    board = record.get("board") or {}
    parts = [
        str(record.get("schema")),
        str(record.get("mode")),
        str(board.get("payloadSha256")),
        str(pins.get("codeRevision")),
        str(pins.get("pipelineFingerprint")),
        str(pins.get("challengerVersion")),
        str(pins.get("csvTreeSha256")),
        str(pins.get("stateTreeSha256")),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def assemble_record(
    *,
    mode: str,
    board: Mapping[str, Any],
    pins: Mapping[str, Any],
    comparison: Mapping[str, Any],
    recorded_at: str,
    challenger: str = CHALLENGER_JOINT,
) -> dict[str, Any]:
    """The ledger line: identity + pins + the comparison, keyed for idempotency."""
    if mode not in LABELS:
        raise ValueError(f"unknown mode {mode!r}")
    record = {
        "schema": SCHEMA,
        "mode": mode,
        "label": LABELS[mode],
        "board": dict(board),
        "pins": {**dict(pins), "challengerVersion": challenger_spec(challenger)["version"]},
        "recordedAt": recorded_at,
        **dict(comparison),
    }
    record["key"] = record_key(record)
    return record
