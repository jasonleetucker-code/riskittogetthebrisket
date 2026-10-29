#!/usr/bin/env python3
"""Source-voting consensus evidence (owner directive 2026-10-19, PR #1817).

Policy under test: agreement between DIFFERENT providers is consensus, not
duplication.  Only credible shared-data-lineage evidence may merge votes.
This script measures, on the CURRENT production board, what each candidate
policy does relative to production ``main``:

* S1 ``main`` — current approved behaviour (code of ``--main-ref``);
* S2 ``old_d2_d3`` — the withdrawn PR #1817 D2 shared cap + D3 offense-vote
  exclusion (code of ``--old-ref``; D4 off, D5 style unset);
* S3 ``revised`` — both IDP providers vote as separate families: main plus the
  two-way alt-evidence fix (this tree: TW on, D4 off, D5 off);
* S4 ``revised_idptc_offense`` — S3 with the IDP Trade Calculator's offense
  votes; D3 is deleted, so the build is S3's and identity is CONFIRMED;
* S5 ``combined`` — TW + D4 + D5 + the approved DLF IDP restore (the release
  hold lifted; ``dlf_offense_only_vote`` forced to 0);
* S5h ``combined_hold_kept`` — S5 with the DLF IDP hold re-applied: this tree's
  RELEASE defaults (the restore is held at release pending the outlier fix);
* DLF ``restore_only`` — every PR flag off except the DLF IDP hold lifted;
* S0 ``all_off`` — this tree with every flag of the PR off (TW, D4, D5, the
  DLF IDP hold re-applied):
  must equal ``main`` at the decision level.

Plus the haircut investigation (old-code D2 on vs off where both IDP
providers vote), the D4 activation gates, the cross-provider family audit, the
IDP-provider similarity diagnostic and the IDPTC-vs-KTC lineage check.

Every board is built through the canonical pipeline
(``build_api_data_contract``) in a subprocess whose import root is that code
tree.  ``main`` and the old PR are extracted with ``git archive`` and read the
SAME inputs as this tree (``CSVs``, ``data``, ``exports``, ``tests`` are
symlinked), so every difference is code, never data.

Usage::

    python scripts/source_voting_consensus_evidence.py \\
        --out docs/sources/evidence/SOURCE_VOTING_CONSENSUS_2026-10-19/results.json

Reusable mode (any flag combination, any code tree, any board; the first
scenario is the baseline unless ``--baseline`` names another)::

    python scripts/source_voting_consensus_evidence.py --board golden \\
        --scenario main='{"tree": "origin/main"}' \\
        --scenario hold='{"env": {"RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE": 1}}' \\
        --scenario defaults \\
        --out /tmp/svc.json

Read-only on the repository.  Exit 0 on success, 2 on error.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import math
import os
import random
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]

_OFFENSE = {"QB", "RB", "WR", "TE"}
_IDP = {"DL", "LB", "DB"}
_D2_MEMBERS = ("idpTradeCalc", "idpShowCombined")

F_TW = "RISKIT_FEATURE_TWO_WAY_ALT_EVIDENCE_RULES"
F_D4 = "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE"
F_D5 = "RISKIT_FEATURE_FANTASYPROS_IDP_UPSTREAM_CLOCK"
F_D2 = "RISKIT_FEATURE_IDP_SHARED_CORRELATION_CAP"  # old tree only
F_D3 = "RISKIT_FEATURE_IDPTC_OFFENSE_VOTE_EXCLUDED"  # old tree only
F_FRESH = "RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING"
# The DLF IDP / DLF Rookie IDP vote hold.  The owner rescinded the policy hold
# and approved the restore 2026-10-19; the restore is held at release (default
# ON) pending the outlier fix (CQ-65).  ``=0`` lifts it (DLF IDP votes).  Every
# scenario below sets it explicitly, so no scenario depends on the default.
F_DLF_HOLD = "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE"
_DLF_IDP = ("dlfIdp", "dlfRookieIdp")

_META_KEYS = (
    "valueContribution",
    "appliedWeight",
    "preFamilyWeight",
    "baseWeight",
    "excludedReason",
    "hampelDropped",
    "familyAdjustment",
    "contributedToBlend",
    "rawRank",
)
_ROW_KEYS = (
    "displayName",
    "canonicalName",
    "position",
    "assetClass",
    "rankDerivedValue",
    "canonicalConsensusRank",
    "canonicalTierId",
    "confidenceBucket",
    "confidenceLabel",
    "singleSourceValuePenaltyApplied",
    "independentSourceCount",
    "freshnessExcludedSources",
    "droppedSources",
    "anchorValue",
    "subgroupBlendValue",
    "alphaShrinkage",
    "sharedLineageCaps",
    "twoWayPlayerBoost",
    "quarantined",
)


# ── worker (runs inside one code tree) ──────────────────────────────────────


def _worker(tree: Path, spec: Mapping[str, Any], out: Path) -> None:
    sys.path.insert(0, str(tree))
    for k, v in (spec.get("env") or {}).items():
        os.environ[k] = str(v)
    from src.api import feature_flags  # noqa: PLC0415

    feature_flags.reload()
    import dataclasses  # noqa: PLC0415

    from src.api import data_contract as dc  # noqa: PLC0415
    from src.sources import freshness as fr  # noqa: PLC0415

    for key in spec.get("dropStyle") or ():
        cfg = fr.load_config()
        cad = cfg.sources.get(key, cfg.default_cadence)
        fr._CONFIG_CACHE.clear()
        fr._CONFIG_CACHE["default"] = dataclasses.replace(
            cfg, sources={**cfg.sources, key: dataclasses.replace(cad, style=None)}
        )
    for key in spec.get("splitFamily") or ():
        for src in dc._RANKING_SOURCES:
            if src.get("key") == key:
                src["correlation_group"] = None
    payload = Path(spec["payload"])
    blob = payload.read_bytes()
    if payload.suffix == ".gz":
        blob = gzip.decompress(blob)
    raw = json.loads(blob)
    contract = dc.build_api_data_contract(copy.deepcopy(raw))
    report = dc.validate_api_data_contract(contract)
    rows = []
    for r in contract.get("playersArray") or []:
        if not isinstance(r, dict) or not r.get("displayName"):
            continue
        row = {k: r.get(k) for k in _ROW_KEYS}
        row["pickProvenance"] = (r.get("pickValueProvenance") or {}).get("class")
        row["sourceKeys"] = sorted(r.get("effectiveSourceRanks") or {})
        row["sites"] = {
            k: v for k, v in (r.get("canonicalSiteValues") or {}).items() if v is not None
        }
        row["meta"] = {
            k: {mk: m.get(mk) for mk in _META_KEYS if mk in m}
            for k, m in (r.get("sourceRankMeta") or {}).items()
            if isinstance(m, dict)
        }
        rows.append(row)
    sw = (contract.get("sourceWeighting") or {}).get("sources") or {}
    families = {
        str(s.get("key") or ""): dc.correlation_group_for(str(s.get("key") or ""))
        for s in dc._RANKING_SOURCES
    }
    out.write_text(
        json.dumps(
            {
                "spec": {k: v for k, v in spec.items() if k != "payload"},
                "rows": rows,
                "families": families,
                "baseWeights": {
                    str(s.get("key") or ""): float(s.get("weight") or 1.0)
                    for s in dc._RANKING_SOURCES
                },
                "sourceWeighting": {
                    k: {
                        kk: v.get(kk)
                        for kk in (
                            "votingRows",
                            "excludedRows",
                            "meanAppliedWeight",
                            "baseWeight",
                            "health",
                        )
                    }
                    | {"players": ((v.get("subsets") or {}).get("players") or {})}
                    for k, v in sw.items()
                    if isinstance(v, dict)
                },
                "validation": {
                    "ok": report.get("ok"),
                    "structurallyOk": report.get("structurallyOk"),
                    "status": report.get("status"),
                    "structuralErrors": list(report.get("structuralErrors") or [])[:20],
                    "sourceHealthErrors": list(report.get("sourceHealthErrors") or []),
                },
            },
            default=str,
        ),
        encoding="utf-8",
    )


# ── orchestration ───────────────────────────────────────────────────────────


def _git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True).stdout
    return out if binary else out.decode().strip()


def _code_tree(ref: str, parent: Path) -> Path:
    """``ref``'s code (src, config, scripts) reading THIS tree's inputs."""
    root = parent / ref.replace("/", "_")
    root.mkdir(parents=True)
    blob = _git("archive", ref, "src", "config", "scripts", binary=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(root, filter="data")  # noqa: S202 -- our own repository
    for name in ("CSVs", "data", "exports", "tests"):
        (root / name).symlink_to(REPO / name)
    return root


class Builder:
    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        self.n = 0

    def build(self, tree: Path, payload: Path, **spec: Any) -> dict[str, Any]:
        self.n += 1
        out = self.scratch / f"build_{self.n}.json"
        cfg = {"payload": str(payload), **spec}
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(tree),
                json.dumps(cfg),
                str(out),
            ],
            cwd=tree,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"build failed ({tree.name} {spec}):\n{proc.stderr[-3000:]}")
        data = json.loads(out.read_text(encoding="utf-8"))
        out.unlink()
        return data


def _klass(row: Mapping[str, Any]) -> str:
    pos = str(row.get("position") or "").upper()
    if row.get("assetClass") == "pick" or pos == "PICK":
        return "pick"
    return "idp" if pos in _IDP else ("offense" if pos in _OFFENSE else "other")


def _rows(b: Mapping[str, Any]) -> dict[str, dict]:
    return {r["displayName"]: r for r in b["rows"]}


def _voters(row: Mapping[str, Any]) -> dict[str, dict]:
    out = {}
    for k, m in (row.get("meta") or {}).items():
        if m.get("excludedReason"):
            continue
        w = m.get("preFamilyWeight", m.get("appliedWeight"))
        if isinstance(w, (int, float)) and w > 0:
            out[k] = m
    return out


def _q(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 3)


_DECISION = (
    "rankDerivedValue",
    "canonicalConsensusRank",
    "canonicalTierId",
    "confidenceBucket",
    "confidenceLabel",
    "sourceKeys",
)


def identity(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    ra, rb = _rows(a), _rows(b)
    diffs: dict[str, int] = {f: 0 for f in _DECISION}
    examples: dict[str, list[str]] = {}
    for name in set(ra) | set(rb):
        x, y = ra.get(name) or {}, rb.get(name) or {}
        for f in _DECISION:
            if x.get(f) != y.get(f):
                diffs[f] += 1
                examples.setdefault(f, []).append(name)
    return {
        "rowsA": len(ra),
        "rowsB": len(rb),
        "decisionFieldDifferences": diffs,
        "identical": not any(diffs.values()) and set(ra) == set(rb),
        "examples": {f: sorted(v)[:5] for f, v in examples.items()},
    }


def compare(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    """Everything the directive asks for, ``alt`` vs ``base``."""
    a, b = _rows(base), _rows(alt)
    moves: list[tuple[float, str, str, str, int, int]] = []
    newly_unpriced, newly_priced = [], []
    conf: dict[str, int] = {}
    haircut_gain: dict[str, int] = {}
    haircut_loss: dict[str, int] = {}
    pick_non_tether = []
    for name, ra in a.items():
        rb = b.get(name)
        if rb is None:
            continue
        va, vb = ra.get("rankDerivedValue"), rb.get("rankDerivedValue")
        k = _klass(ra)
        if va and not vb:
            newly_unpriced.append(name)
        elif vb and not va:
            newly_priced.append(name)
        elif va and vb and va != vb:
            moves.append((100.0 * (vb - va) / va, name, k, str(ra.get("position")), va, vb))
            if k == "pick" and rb.get("pickProvenance") not in (
                "rookie_pool_tether",
                "alias_suppressed",
            ):
                pick_non_tether.append(name)
        if ra.get("confidenceBucket") != rb.get("confidenceBucket"):
            key = f"{k}:{ra.get('confidenceBucket')}->{rb.get('confidenceBucket')}"
            conf[key] = conf.get(key, 0) + 1
        ha, hb = (
            bool(ra.get("singleSourceValuePenaltyApplied")),
            bool(rb.get("singleSourceValuePenaltyApplied")),
        )
        if hb and not ha:
            haircut_gain[k] = haircut_gain.get(k, 0) + 1
        if ha and not hb:
            haircut_loss[k] = haircut_loss.get(k, 0) + 1
    by_class: dict[str, Any] = {}
    for k in ("offense", "idp", "pick", "other"):
        xs = [abs(m[0]) for m in moves if m[2] == k]
        if not xs:
            by_class[k] = {"moved": 0}
            continue
        by_class[k] = {
            "moved": len(xs),
            "absPctP50": _q(xs, 0.5),
            "absPctP90": _q(xs, 0.9),
            "absPctP99": _q(xs, 0.99),
            "absPctMax": round(max(xs), 2),
        }
    by_pos: dict[str, Any] = {}
    for pos in sorted({m[3] for m in moves}):
        xs = [m[0] for m in moves if m[3] == pos]
        by_pos[pos] = {
            "moved": len(xs),
            "signedPctP50": _q(xs, 0.5),
            "absPctMax": round(max(abs(x) for x in xs), 2),
        }

    def top(rows: Mapping[str, dict], n: int) -> set[str]:
        return {k for k, r in rows.items() if (r.get("canonicalConsensusRank") or 10**9) <= n}

    sw_a, sw_b = base.get("sourceWeighting") or {}, alt.get("sourceWeighting") or {}
    sources = {}
    for key in sorted(set(sw_a) | set(sw_b)):
        x, y = sw_a.get(key) or {}, sw_b.get(key) or {}
        if (x.get("votingRows"), x.get("meanAppliedWeight")) != (
            y.get("votingRows"),
            y.get("meanAppliedWeight"),
        ):
            sources[key] = {
                "votingRows": [x.get("votingRows"), y.get("votingRows")],
                "meanAppliedWeight": [x.get("meanAppliedWeight"), y.get("meanAppliedWeight")],
            }
    hunter = {}
    for name in ("Travis Hunter",):
        if name in a or name in b:
            hunter[name] = {
                "base": (a.get(name) or {}).get("rankDerivedValue"),
                "alt": (b.get(name) or {}).get("rankDerivedValue"),
                "altAudit": (b.get(name) or {}).get("twoWayPlayerBoost"),
            }
    return {
        "valuesMoved": len(moves),
        "offensePlayersMoved": by_class["offense"]["moved"],
        "defensePlayersMoved": by_class["idp"]["moved"],
        "byClass": by_class,
        "byPosition": by_pos,
        "largest": [
            {"name": n, "class": k, "position": p, "from": x, "to": y, "pct": round(d, 2)}
            for d, n, k, p, x, y in sorted(moves, key=lambda m: -abs(m[0]))[:12]
        ],
        "newlyUnpriced": newly_unpriced,
        "newlyPriced": newly_priced,
        "top50": {
            "entered": sorted(top(b, 50) - top(a, 50)),
            "left": sorted(top(a, 50) - top(b, 50)),
        },
        "top200": {
            "entered": sorted(top(b, 200) - top(a, 200)),
            "left": sorted(top(a, 200) - top(b, 200)),
        },
        "confidenceBucketFlips": dict(sorted(conf.items())),
        "singleSourceHaircut": {"gained": haircut_gain, "lost": haircut_loss},
        "picksMovedNotTether": pick_non_tether,
        "sourceVoteChanges": sources,
        "twoWay": hunter,
    }


def weight_violations(board: Mapping[str, Any]) -> dict[str, Any]:
    """Any source above its approved weight, or a family above one provider."""
    fam, base = board["families"], board["baseWeights"]
    over_source, over_family = [], []
    for name, row in _rows(board).items():
        totals: dict[str, float] = {}
        caps: dict[str, float] = {}
        for key, m in _voters(row).items():
            if m.get("hampelDropped") or m.get("contributedToBlend") is False:
                continue
            w = float(m.get("appliedWeight") or 0.0)
            approved = float(base.get(key, 1.0))
            if w > approved + 1e-3:
                over_source.append(f"{name}:{key}:{w}")
            f = fam.get(key, key)
            totals[f] = totals.get(f, 0.0) + w
            caps[f] = max(caps.get(f, 0.0), approved)
        for f, t in totals.items():
            if t > caps[f] + 1e-3:
                over_family.append(f"{name}:{f}:{round(t, 4)}")
    return {
        "sourcesAboveApprovedWeight": over_source[:20],
        "sourcesAboveApprovedWeightCount": len(over_source),
        "familiesAboveOneProvider": over_family[:20],
        "familiesAboveOneProviderCount": len(over_family),
    }


# ── haircut investigation ───────────────────────────────────────────────────


def haircut_investigation(
    off: Mapping[str, Any],
    on: Mapping[str, Any],
    revised: Mapping[str, Any],
    restored: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Every row the old D2 moved by more than 30%, decomposed into (a) the
    grouping, (b) the haircut step and (c) voting eligibility.

    ``revised`` keeps the DLF IDP hold so the comparison isolates the D2
    grouping; ``restored`` (optional) is the same policy with DLF IDP voting."""
    a, b, r = _rows(off), _rows(on), _rows(revised)
    rr = _rows(restored) if restored is not None else {}
    fam = off["families"]
    out = []
    counts = {"grouping": 0, "haircutStep": 0, "eligibilityContributes": 0}
    for name, ra in a.items():
        rb = b.get(name) or {}
        va, vb = ra.get("rankDerivedValue"), rb.get("rankDerivedValue")
        if not va or not vb or abs(vb - va) / va <= 0.30:
            continue
        vote_a = sorted(_voters(ra))
        vote_b = sorted(_voters(rb))
        withheld = sorted(k for k, m in (ra.get("meta") or {}).items() if m.get("excludedReason"))
        engaged = bool(rb.get("sharedLineageCaps"))
        fam_before = sorted({fam.get(k, k) for k in vote_a + withheld})
        fam_after = sorted(
            {
                ("idpShow" if engaged and k in _D2_MEMBERS else fam.get(k, k))
                for k in vote_b + withheld
            }
        )
        observed_not_voting = sorted(
            k for k in (ra.get("sites") or {}) if k not in (ra.get("meta") or {}) and fam.get(k)
        )
        ratio = vb / va
        grouping = len(fam_before) >= 2 and len(fam_after) == 1 and engaged
        step = 0.28 <= ratio <= 0.32
        counts["grouping"] += grouping
        counts["haircutStep"] += step
        counts["eligibilityContributes"] += bool(observed_not_voting or withheld)
        out.append(
            {
                "name": name,
                "position": ra.get("position"),
                "valueBefore": va,
                "valueOldD2": vb,
                "valueRevised": (r.get(name) or {}).get("rankDerivedValue"),
                "valueRevisedDlfRestored": (rr.get(name) or {}).get("rankDerivedValue"),
                "ratio": round(ratio, 4),
                "votingBefore": vote_a,
                "votingOldD2": vote_b,
                "withheld": withheld,
                "observedButNotVoting": observed_not_voting,
                "familiesBefore": fam_before,
                "familiesOldD2": fam_after,
                "haircutBefore": bool(ra.get("singleSourceValuePenaltyApplied")),
                "haircutOldD2": bool(rb.get("singleSourceValuePenaltyApplied")),
                "center": rb.get("anchorValue"),
                "arithmetic": (
                    f"C={rb.get('anchorValue')} x 0.30 = "
                    f"{round(0.30 * (rb.get('anchorValue') or 0))} (published {vb})"
                ),
                "causes": {
                    "a_grouping": grouping,
                    "b_haircut_step": step,
                    "c_eligibility": observed_not_voting + withheld,
                },
            }
        )
    out.sort(key=lambda d: d["ratio"])
    return {"rowsMovedOver30Pct": len(out), "causeCounts": counts, "rows": out}


def haircut_census(board: Mapping[str, Any]) -> dict[str, Any]:
    """Who carries the 30% retention on a board, and why."""
    fam = board["families"]
    by_class: dict[str, int] = {}
    present_not_voting = 0
    examples = []
    for name, row in _rows(board).items():
        if not row.get("singleSourceValuePenaltyApplied"):
            continue
        k = _klass(row)
        by_class[k] = by_class.get(k, 0) + 1
        observed = [
            s for s in (row.get("sites") or {}) if s not in (row.get("meta") or {}) and fam.get(s)
        ]
        if observed:
            present_not_voting += 1
            if len(examples) < 8:
                examples.append(
                    {"name": name, "voting": sorted(_voters(row)), "notVoting": observed}
                )
    return {
        "haircutRowsByClass": by_class,
        "haircutRowsWithObservedButNotVotingSources": present_not_voting,
        "examples": examples,
    }


# ── D4 gates ────────────────────────────────────────────────────────────────


def d4_gates(off: Mapping[str, Any], d4: Mapping[str, Any], tree: Path) -> dict[str, Any]:
    key = "dlfValuesSfTep"
    a, b = _rows(off), _rows(d4)
    fam = d4["families"]
    votes_by_class: dict[str, int] = {}
    dropped = 0
    fam_max = 0.0
    idp_moves, pick_non_tether, second_dlf = [], [], []
    for name, rb in b.items():
        ra = a.get(name) or {}
        m = (rb.get("meta") or {}).get(key)
        if m and not m.get("excludedReason"):
            votes_by_class[_klass(rb)] = votes_by_class.get(_klass(rb), 0) + 1
            dropped += bool(m.get("hampelDropped"))
        dlf_total = sum(
            float(mm.get("appliedWeight") or 0.0)
            for kk, mm in _voters(rb).items()
            if fam.get(kk) == "dlf" and not mm.get("hampelDropped")
        )
        fam_max = max(fam_max, dlf_total)
        fams_a = {fam.get(k, k) for k, mm in _voters(ra).items() if not mm.get("hampelDropped")}
        fams_b = [fam.get(k, k) for k, mm in _voters(rb).items() if not mm.get("hampelDropped")]
        if (
            fams_b.count("dlf") > 0
            and "dlf" in fams_a
            and rb.get("independentSourceCount", 0) > (ra.get("independentSourceCount") or 0)
        ):
            added = set(fams_b) - fams_a
            if "dlf" in added:
                second_dlf.append(name)
        if ra.get("rankDerivedValue") != rb.get("rankDerivedValue"):
            if _klass(rb) == "idp":
                idp_moves.append(name)
            elif _klass(rb) == "pick" and rb.get("pickProvenance") not in (
                "rookie_pool_tether",
                "alias_suppressed",
            ):
                pick_non_tether.append(name)
    votes = sum(votes_by_class.values())
    diff = compare(off, d4)
    off_moves = [
        abs(x["pct"]) for x in diff["largest"] if x["class"] == "offense"
    ]  # top movers only; quantiles come from byClass
    top50 = [
        abs(
            100.0 * (b[n]["rankDerivedValue"] - a[n]["rankDerivedValue"]) / a[n]["rankDerivedValue"]
        )
        for n, r in a.items()
        if (r.get("canonicalConsensusRank") or 10**9) <= 50
        and r.get("rankDerivedValue")
        and (b.get(n) or {}).get("rankDerivedValue")
    ]
    # Source timestamps and completeness.
    sw = (d4.get("sourceWeighting") or {}).get(key) or {}
    players = sw.get("players") or {}
    path = REPO / "CSVs" / "site_raw" / f"{key}.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    vals = [float(r["value"]) for r in rows if r.get("value")]
    pos: dict[str, int] = {}
    for r in rows:
        pos[r.get("pos") or ""] = pos.get(r.get("pos") or "", 0) + 1
    # Longitudinal stability, from the canonical evaluation module.
    spec = importlib.util.spec_from_file_location(
        "idp_rehab_eval", tree / "scripts" / "idp_rehab_eval.py"
    )
    rehab = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(rehab)
    history = rehab.dlf_values_publication_history()
    pkg = package_model_check(off, d4)
    gates = {
        "timestamps": {
            "measured": {
                k: players.get(k)
                for k in (
                    "publicationStyle",
                    "freshnessClock",
                    "sourceDataAsOf",
                    "ageHours",
                    "expectedCadenceHours",
                    "freshness",
                    "state",
                )
            }
            | {"health": sw.get("health")},
            "pass": players.get("state") == "ON_SCHEDULE" and sw.get("health") == "HEALTHY",
        },
        "completeness": {
            "measured": {
                "rows": len(rows),
                "byPosition": pos,
                "nonPositive": sum(1 for v in vals if v <= 0),
                "pickRows": sum(1 for r in rows if str(r.get("name", "")).strip()[:4].isdigit()),
            },
            "pass": len(rows) >= 300
            and all(pos.get(p, 0) > 0 for p in ("QB", "RB", "WR", "TE"))
            and not any(v <= 0 for v in vals)
            and not any(str(r.get("name", "")).strip()[:4].isdigit() for r in rows),
        },
        "longitudinalStability": {"measured": history, "pass": None},
        "topPlayerMovement": {
            "measured": {
                "top50MaxAbsPct": round(max(top50), 2) if top50 else 0.0,
                "top50MembershipSwaps": len(diff["top50"]["entered"]),
                "offenseAbsPctP90": diff["byClass"]["offense"].get("absPctP90"),
            },
            "pass": (max(top50) if top50 else 0.0) <= 5.0
            and len(diff["top50"]["entered"]) <= 2
            and (diff["byClass"]["offense"].get("absPctP90") or 0.0) <= 3.0,
        },
        "outlierDiagnostic": {
            "measured": {"hampelDropRate": round(dropped / votes, 4) if votes else None},
            "pass": votes > 0 and dropped / votes <= 0.05,
        },
        "nonInterference": {
            "measured": {
                "votesByClass": votes_by_class,
                "idpValueMoves": idp_moves,
                "picksMovedNotTether": pick_non_tether,
            },
            "pass": set(votes_by_class) <= {"offense"} and not idp_moves and not pick_non_tether,
        },
        "oneDlfFamily": {
            "measured": {
                "maxDlfFamilyAppliedWeight": round(fam_max, 4),
                "secondDlfFamilyRows": second_dlf,
            },
            "pass": fam_max <= 1.0 + 1e-3 and not second_dlf,
        },
        "packageModel": {
            "measured": pkg,
            "pass": pkg["invariantFailures"] == 0 and pkg["sideFlips"] <= 0.01 * pkg["pairings"],
        },
        "contract": {
            "measured": d4.get("validation"),
            "pass": bool((d4.get("validation") or {}).get("structurallyOk")),
        },
    }
    versions = history.get("distinctContentVersions") or []
    sp = [v["spearmanVsPrevious"] for v in versions if v.get("spearmanVsPrevious") is not None]
    ov = [v["top24OverlapVsPrevious"] for v in versions if "top24OverlapVsPrevious" in v]
    gates["longitudinalStability"]["measured"] = {
        "distinctReleases": len(versions),
        "firstRelease": versions[0]["at"] if versions else None,
        "lastRelease": versions[-1]["at"] if versions else None,
        "consecutiveSpearmanMin": min(sp) if sp else None,
        "consecutiveSpearmanMax": max(sp) if sp else None,
        "top24OverlapMin": min(ov) if ov else None,
        "top24OverlapMax": max(ov) if ov else None,
    }
    gates["longitudinalStability"]["pass"] = (
        len(versions) >= 10 and bool(sp) and min(sp) >= 0.95 and bool(ov) and min(ov) >= 20
    )
    gates["_offenseLargestMovers"] = off_moves
    gates["_diff"] = diff
    return gates


def package_model_check(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    """The ACTIVE package model over a fixed seeded grid of pairings (same
    asset names both sides; only the board values differ)."""
    from src.valuation_math import package_model as pm  # noqa: PLC0415

    a, b = _rows(base), _rows(alt)
    pool = sorted(
        (n for n, r in a.items() if _klass(r) == "offense" and r.get("rankDerivedValue")),
        key=lambda n: -a[n]["rankDerivedValue"],
    )[:200]
    pool = [n for n in pool if (b.get(n) or {}).get("rankDerivedValue")]
    rng = random.Random(20261018)
    shapes = ((1, 2), (2, 3), (1, 3), (2, 2))
    flips = band = invariant_failures = 0
    for _ in range(2000):
        s, t = rng.choice(shapes)
        picks = rng.sample(pool, s + t)
        left, right = picks[:s], picks[s:]
        res = []
        for rows in (a, b):
            lv = [rows[n]["rankDerivedValue"] for n in left]
            rv = [rows[n]["rankDerivedValue"] for n in right]
            la, ra_, lva, rva = pm.adjusted_pair_totals(lv, rv)
            if lva < 0 or rva < 0 or la < sum(lv) - 1e-9 or ra_ < sum(rv) - 1e-9:
                invariant_failures += 1
            res.append(la - ra_)
        g0, g1 = res
        if (g0 > 0) != (g1 > 0) and g0 != 0 and g1 != 0:
            flips += 1
        if (abs(g0) <= 250) != (abs(g1) <= 250):
            band += 1
    return {
        "activeModel": pm.active_model_id(),
        "pairings": 2000,
        "invariantFailures": invariant_failures,
        "sideFlips": flips,
        "even250BandCrossings": band,
    }


# ── diagnostics ─────────────────────────────────────────────────────────────


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0 + 1
            i = j + 1
        return r

    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 4) if den else None


def _board(
    path: Path, *, value_col: str | None = None, rank_col: str | None = None
) -> dict[str, float]:
    """``{match key: score}`` (higher = better) from one site CSV."""
    sys.path.insert(0, str(REPO))
    from src.api.data_contract import _canonical_match_key  # noqa: PLC0415

    out: dict[str, float] = {}
    for r in csv.DictReader(path.open(encoding="utf-8")):
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        try:
            score = float(r[value_col]) if value_col else -float(r[rank_col])  # type: ignore[index]
        except (TypeError, ValueError, KeyError):
            continue
        key = _canonical_match_key(name)
        out[key] = max(out.get(key, score), score)
    return out


def similarity_diagnostic() -> dict[str, Any]:
    """IDP Trade Calculator vs The IDP Show order agreement on common players.
    A DIAGNOSTIC: similarity is not lineage and decides no vote."""
    site = REPO / "CSVs" / "site_raw"
    idptc = _board(site / "idpTradeCalc.csv", value_col="value")
    out = {}
    for label, path in (
        ("idpShow_idpOnly", site / "idpShow.csv"),
        ("idpShowCombined", site / "idpShowCombined.csv"),
    ):
        if not path.exists():
            continue
        show = _board(path, rank_col="rank")
        common = sorted(set(idptc) & set(show))
        xs, ys = [idptc[k] for k in common], [show[k] for k in common]
        conc = disc = 0
        for i in range(len(common)):
            for j in range(i + 1, len(common)):
                dx, dy = xs[i] - xs[j], ys[i] - ys[j]
                if dx == 0 or dy == 0:
                    continue
                if (dx > 0) == (dy > 0):
                    conc += 1
                else:
                    disc += 1
        out[label] = {
            "commonPlayers": len(common),
            "spearman": _spearman(xs, ys),
            "identicalRelativeOrderShare": round(conc / (conc + disc), 4) if conc + disc else None,
        }
    return out


def idptc_ktc_lineage_check() -> dict[str, Any]:
    """Concrete republication evidence only: IDENTICAL raw offense values
    (not similar ones), and broad-update timestamps that mirror KTC's."""
    site = REPO / "CSVs" / "site_raw"
    idptc = _board(site / "idpTradeCalc.csv", value_col="value")
    out: dict[str, Any] = {}
    for label in ("ktc", "ktcCrowdSfTep", "ktcSfTep"):
        path = site / f"{label}.csv"
        if not path.exists():
            continue
        ktc = _board(path, value_col="value")
        common = [k for k in set(idptc) & set(ktc) if ktc[k] > 0]
        exact = sum(1 for k in common if idptc[k] == ktc[k])
        within1 = sum(1 for k in common if abs(idptc[k] - ktc[k]) <= 0.01 * ktc[k])
        out[label] = {"commonRows": len(common), "exactlyEqual": exact, "within1Pct": within1}
    state = REPO / "data" / "scrape_state"

    def broad(key: str) -> list[str]:
        p = state / f"{key}_dataset.json"
        if not p.exists():
            return []
        d = json.loads(p.read_text(encoding="utf-8"))
        subs = d.get("subsets") or {}
        ev = (subs.get("players") or {}).get("changeHistory") or d.get("changeHistory") or []
        return sorted(e.get("at") for e in ev if e.get("broad"))

    from datetime import datetime  # noqa: PLC0415

    def ts(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    itc, ktcb = broad("idpTradeCalc"), broad("ktcCrowdSfTep")
    lags = []
    for t in itc:
        prior = [k for k in ktcb if ts(k) <= ts(t)]
        if prior:
            lags.append(round((ts(t) - ts(prior[-1])).total_seconds() / 3600.0, 1))
    out["broadChangeTimestamps"] = {
        "note": (
            "uninformative by construction: both clocks are OUR fetch times, and KTC Crowd "
            "changes broadly at almost every 2-hourly fetch, so every IDPTC broad change "
            "coincides with one; this cannot evidence mirroring either way"
        ),
        "idpTradeCalcBroadChanges": len(itc),
        "ktcCrowdBroadChanges": len(ktcb),
        "hoursSincePriorKtcBroadChange": lags[-20:],
        "medianLagHours": _q(lags, 0.5),
    }
    return out


def family_audit(board: Mapping[str, Any]) -> list[dict[str, Any]]:
    sys.path.insert(0, str(REPO))
    from src.sources.source_census import provider_of  # noqa: PLC0415

    lineage = json.loads(
        (REPO / "config" / "sources" / "source_lineage.json").read_text(encoding="utf-8")
    )
    rel_by_pair: dict[str, list[dict]] = {}
    for rel in lineage["relations"]:
        for s in rel["sources"]:
            rel_by_pair.setdefault(s, []).append(rel)
    groups: dict[str, list[str]] = {}
    for key, fam in board["families"].items():
        groups.setdefault(fam, []).append(key)
    out = []
    for fam, keys in sorted(groups.items()):
        providers = {k: provider_of(k) for k in keys}
        if len(set(providers.values())) <= 1:
            continue
        head = [k for k in keys if k == fam] or keys[:1]
        for k in keys:
            if providers[k] == providers[head[0]]:
                continue
            rels = [
                {"id": r["id"], "relation": r["relation"], "classification": r["classification"]}
                for r in rel_by_pair.get(k, [])
                if any(h in r["sources"] for h in keys if providers[h] != providers[k])
            ]
            out.append(
                {
                    "family": fam,
                    "member": k,
                    "memberProvider": providers[k],
                    "familyProviders": sorted(set(providers.values()) - {None}),
                    "relations": rels,
                }
            )
    return out


# ── DLF IDP restore decomposition ───────────────────────────────────────────


def _dropped(row: Mapping[str, Any]) -> set[str]:
    out = {k for k, m in (row.get("meta") or {}).items() if m.get("hampelDropped")}
    ds = row.get("droppedSources")
    if isinstance(ds, (list, tuple)):
        out |= {str(x) for x in ds}
    elif isinstance(ds, dict):
        out |= {str(x) for x in ds}
    return out


def dlf_restore_decomposition(held: Mapping[str, Any], restored: Mapping[str, Any]) -> dict:
    """Every value the DLF IDP restore moved, split by cause.

    * ``dlfOwnVote`` — DLF IDP / DLF Rookie IDP gained a vote on the row and no
      OTHER source's Hampel verdict changed: the move is DLF's own opinion
      entering the blend.
    * ``outlierSideEffect`` — another source's vote was newly dropped (or
      restored) by the outlier filter.  The extra voter changed the panel the
      Hampel test runs on (n crossing 4 turns the filter on); the move is
      partly or wholly someone else's opinion leaving the blend.
    * ``pickTether`` — a current-year slot pick re-tethered to the merged
      rookie pool, which IDP rookies are part of.
    * ``other`` — none of the above (e.g. IDP rank translation through the
      cross-market backbone, which shifts with the IDP pool).
    """
    a, b = _rows(held), _rows(restored)
    cats: dict[str, list[dict]] = {
        "dlfOwnVote": [],
        "outlierSideEffect": [],
        "pickTether": [],
        "other": [],
    }
    newly_dropped: dict[str, int] = {}
    newly_kept: dict[str, int] = {}
    for name, ra in a.items():
        rb = b.get(name)
        if rb is None:
            continue
        va, vb = ra.get("rankDerivedValue"), rb.get("rankDerivedValue")
        if not va or not vb or va == vb:
            continue
        gained = sorted(k for k in _DLF_IDP if k in _voters(rb) and k not in _voters(ra))
        da = _dropped(ra) - set(_DLF_IDP)
        db = _dropped(rb) - set(_DLF_IDP)
        for k in db - da:
            newly_dropped[k] = newly_dropped.get(k, 0) + 1
        for k in da - db:
            newly_kept[k] = newly_kept.get(k, 0) + 1
        entry = {
            "name": name,
            "position": ra.get("position"),
            "from": va,
            "to": vb,
            "pct": round(100.0 * (vb - va) / va, 2),
            "dlfVotesGained": gained,
            "otherSourcesNewlyDropped": sorted(db - da),
            "otherSourcesNewlyKept": sorted(da - db),
            "dlfDroppedAfter": sorted(_dropped(rb) & set(_DLF_IDP)),
        }
        if db != da:
            cats["outlierSideEffect"].append(entry)
        elif gained:
            cats["dlfOwnVote"].append(entry)
        elif _klass(ra) == "pick":
            cats["pickTether"].append(entry)
        else:
            cats["other"].append(entry)

    def summary(rows: list[dict]) -> dict[str, Any]:
        xs = [abs(r["pct"]) for r in rows]
        return {
            "moved": len(rows),
            "absPctP50": _q(xs, 0.5),
            "absPctP90": _q(xs, 0.9),
            "absPctMax": round(max(xs), 2) if xs else None,
            "over30Pct": sum(1 for x in xs if x > 30.0),
            "largest": sorted(rows, key=lambda r: -abs(r["pct"]))[:10],
        }

    dlf_votes = {
        k: [sum(1 for r in bd["rows"] if k in _voters(r)) for bd in (held, restored)]
        for k in _DLF_IDP
    }
    return {
        "dlfIdpVotingRows": dlf_votes,
        "byCause": {k: summary(v) for k, v in cats.items()},
        "otherSourceVotesNewlyDroppedByOutlierFilter": dict(sorted(newly_dropped.items())),
        "otherSourceVotesNewlyKeptByOutlierFilter": dict(sorted(newly_kept.items())),
        "rowsOver30Pct": sorted(
            ({"cause": c, **e} for c, rows in cats.items() for e in rows if abs(e["pct"]) > 30.0),
            key=lambda e: -abs(e["pct"]),
        ),
    }


# ── reusable scenario mode ──────────────────────────────────────────────────


def _resolve_tree(ref: str, scratch: Path, cache: dict[str, Path]) -> Path:
    """``.`` is this working tree; anything else is a git ref."""
    if ref in (".", "worktree"):
        return REPO
    if ref not in cache:
        cache[ref] = _code_tree(ref, scratch)
    return cache[ref]


def _resolve_board(spec: str | None) -> Path:
    if spec in (None, "", "current"):
        return sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))[-1]
    if spec == "golden":
        return REPO / "tests" / "fixtures" / "golden" / "input_export.json.gz"
    return Path(spec).resolve()


def run_custom(payload: Path, scenarios: list[str], baseline: str | None, out: Path) -> int:
    """Build any flag combination on any code tree and compare to a baseline.

    Each ``--scenario`` is ``NAME`` or ``NAME={json}`` where the JSON may hold
    ``tree`` (``.`` = this working tree, default; else a git ref), ``env`` (flag
    environment variables), ``dropStyle`` and ``splitFamily``.  The first
    scenario is the baseline unless ``--baseline`` names another.
    """
    specs: dict[str, dict[str, Any]] = {}
    for item in scenarios:
        name, _, js = item.partition("=")
        specs[name] = json.loads(js) if js else {}
    base_name = baseline or next(iter(specs))
    if base_name not in specs:
        raise SystemExit(f"baseline {base_name!r} is not a scenario")
    with tempfile.TemporaryDirectory(prefix="svc-") as tmp:
        scratch = Path(tmp)
        trees: dict[str, Path] = {}
        b = Builder(scratch)
        built = {
            name: b.build(
                _resolve_tree(str(spec.get("tree", ".")), scratch, trees),
                payload,
                **{k: v for k, v in spec.items() if k != "tree"},
            )
            for name, spec in specs.items()
        }
        base = built[base_name]
        report = {
            "schema": "source-voting-consensus/custom-v1",
            "pins": {
                "code": _git("rev-parse", "HEAD"),
                "workingTreeDirty": bool(_git("status", "--porcelain")),
                "trees": {ref: _git("rev-parse", ref) for ref in trees},
                "payload": str(
                    payload.relative_to(REPO) if payload.is_relative_to(REPO) else payload
                ),
                "payloadSha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            },
            "baseline": {"name": base_name, "spec": specs[base_name]},
            "scenarios": {
                name: {
                    "spec": specs[name],
                    "identityWithBaseline": identity(base, bd),
                    "vsBaseline": compare(base, bd)
                    | {"weights": weight_violations(bd), "validation": bd["validation"]},
                    "dlfRestoreDecomposition": dlf_restore_decomposition(base, bd),
                }
                for name, bd in built.items()
                if name != base_name
            },
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--worker", nargs=3, metavar=("TREE", "SPEC", "OUT"))
    ap.add_argument("--payload", type=Path, default=None)
    ap.add_argument(
        "--board",
        default=None,
        help="current (default), golden, or a payload path; overrides --payload",
    )
    ap.add_argument(
        "--scenario",
        action="append",
        default=[],
        help='reusable mode: NAME or NAME=\'{"tree": ".", "env": {...}}\' (repeatable)',
    )
    ap.add_argument("--baseline", default=None, help="reusable mode: baseline scenario name")
    ap.add_argument("--main-ref", default="origin/main")
    ap.add_argument("--old-ref", default="eb44b5421f")
    ap.add_argument("--out", type=Path, required=False)
    args = ap.parse_args(argv)
    if args.worker:
        tree, spec, out = args.worker
        _worker(Path(tree), json.loads(spec), Path(out))
        return 0
    if args.out is None:
        ap.error("--out is required")
    payload = (
        _resolve_board(args.board)
        if args.board is not None
        else (args.payload or _resolve_board(None))
    )
    if args.scenario:
        return run_custom(payload, args.scenario, args.baseline, args.out)
    golden = REPO / "tests" / "fixtures" / "golden" / "input_export.json.gz"
    sys.path.insert(0, str(REPO))
    with tempfile.TemporaryDirectory(prefix="svc-") as tmp:
        scratch = Path(tmp)
        main_tree = _code_tree(args.main_ref, scratch)
        old_tree = _code_tree(args.old_ref, scratch)
        b = Builder(scratch)
        # Every flag of the PR off, the DLF IDP hold re-applied: must be main.
        off = {F_TW: 0, F_D4: 0, F_D5: 0, F_DLF_HOLD: 1}
        hold = {F_DLF_HOLD: 1}
        restore = {F_DLF_HOLD: 0}
        old_d2d3 = {"env": {F_D2: 1, F_D3: 1, F_D4: 0}, "dropStyle": ["fantasyProsIdp"]}
        boards: dict[str, dict[str, Any]] = {}
        for label, pl in (("current", payload), ("golden", golden)):
            boards[label] = {
                "S1_main": b.build(main_tree, pl),
                "S0_all_off": b.build(REPO, pl, env=off),
                "S2_old_d2_d3": b.build(old_tree, pl, **old_d2d3),
                "S3_revised": b.build(REPO, pl, env={F_TW: 1, F_D4: 0, F_D5: 0, **hold}),
                "S5_combined": b.build(REPO, pl, env=restore),
                "S5_combined_hold_kept": b.build(REPO, pl, env=hold),
                "DLF_restore_only": b.build(
                    REPO, pl, env={F_TW: 0, F_D4: 0, F_D5: 0, F_DLF_HOLD: 0}
                ),
                "D4_only": b.build(REPO, pl, env={F_TW: 0, F_D4: 1, F_D5: 0, **hold}),
                "D5_only": b.build(REPO, pl, env={F_TW: 0, F_D4: 0, F_D5: 1, **hold}),
            }
        # Haircut investigation: where both IDP providers vote.
        old_base = {"env": {F_D2: 0, F_D3: 0, F_D4: 0}, "dropStyle": ["fantasyProsIdp"]}
        old_d2 = {"env": {F_D2: 1, F_D3: 0, F_D4: 0}, "dropStyle": ["fantasyProsIdp"]}
        engaged = {F_FRESH: 0}
        hc = {
            "golden": haircut_investigation(
                b.build(old_tree, golden, **old_base),
                b.build(old_tree, golden, **old_d2),
                boards["golden"]["S5_combined_hold_kept"],
                boards["golden"]["S5_combined"],
            ),
            "currentFreshnessOff": haircut_investigation(
                b.build(
                    old_tree,
                    payload,
                    env={**old_base["env"], **engaged},
                    dropStyle=["fantasyProsIdp"],
                ),
                b.build(
                    old_tree,
                    payload,
                    env={**old_d2["env"], **engaged},
                    dropStyle=["fantasyProsIdp"],
                ),
                b.build(REPO, payload, env={F_FRESH: 0, **hold}),
                b.build(REPO, payload, env={F_FRESH: 0, **restore}),
            ),
        }
        # Cross-provider family audit + split impact.
        cur = boards["current"]
        audit = family_audit(cur["S5_combined"])
        engaged_revised = b.build(REPO, payload, env={F_FRESH: 0, **restore})
        for entry in audit:
            # With freshness weighting rolled back every member votes at its
            # base weight: the impact the grouping has whenever it is live.
            split_e = b.build(
                REPO, payload, env={F_FRESH: 0, **restore}, splitFamily=[entry["member"]]
            )
            entry["boardImpactIfSplitFreshnessOff"] = {
                k: v
                for k, v in compare(engaged_revised, split_e).items()
                if k
                in (
                    "valuesMoved",
                    "offensePlayersMoved",
                    "defensePlayersMoved",
                    "byClass",
                    "largest",
                )
            }
            entry["memberVotesFreshnessOff"] = sum(
                1 for r in engaged_revised["rows"] if entry["member"] in _voters(r)
            )
            split = b.build(REPO, payload, env=restore, splitFamily=[entry["member"]])
            entry["boardImpactIfSplit"] = {
                k: v
                for k, v in compare(cur["S5_combined"], split).items()
                if k
                in (
                    "valuesMoved",
                    "offensePlayersMoved",
                    "defensePlayersMoved",
                    "byClass",
                    "largest",
                )
            }
            entry["memberVotesOnBoard"] = sum(
                1 for r in cur["S5_combined"]["rows"] if entry["member"] in _voters(r)
            )
        report: dict[str, Any] = {
            "schema": "source-voting-consensus/v1",
            "pins": {
                "code": _git("rev-parse", "HEAD"),
                "workingTreeDirty": bool(_git("status", "--porcelain")),
                "mainRef": args.main_ref,
                "mainSha": _git("rev-parse", args.main_ref),
                "oldRef": args.old_ref,
                "oldSha": _git("rev-parse", args.old_ref),
                "payload": str(payload.relative_to(REPO)),
                "payloadSha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "goldenSha256": hashlib.sha256(gzip.decompress(golden.read_bytes())).hexdigest(),
            },
            "boards": {},
            "haircutInvestigation": hc,
            "haircutCensus": {
                "currentMain": haircut_census(cur["S1_main"]),
                "currentCombined": haircut_census(cur["S5_combined"]),
            },
            "familyAudit": audit,
            "similarityDiagnostic": similarity_diagnostic(),
            "idptcKtcLineageCheck": idptc_ktc_lineage_check(),
            "d4Gates": {
                label: {
                    k: v
                    for k, v in d4_gates(
                        boards[label]["S0_all_off"], boards[label]["D4_only"], REPO
                    ).items()
                    if not k.startswith("_")
                }
                for label in ("current",)
            },
        }
        for label, bs in boards.items():
            main_b = bs["S1_main"]
            report["boards"][label] = {
                "allOffIdentityWithMain": identity(main_b, bs["S0_all_off"]),
                "S4_equals_S3": "S4 is S3's build: D3 is deleted, so the IDP Trade Calculator's offense votes are main's",
                "idptcOffenseVotes": {
                    k: sum(
                        1
                        for r in bs[k]["rows"]
                        if _klass(r) == "offense" and "idpTradeCalc" in (r.get("meta") or {})
                    )
                    for k in (
                        "S1_main",
                        "S2_old_d2_d3",
                        "S3_revised",
                        "S5_combined",
                        "DLF_restore_only",
                    )
                },
                "scenarios": {
                    k: compare(main_b, bs[k])
                    | {"weights": weight_violations(bs[k]), "validation": bs[k]["validation"]}
                    for k in (
                        "S0_all_off",
                        "S2_old_d2_d3",
                        "S3_revised",
                        "S5_combined",
                        "S5_combined_hold_kept",
                        "DLF_restore_only",
                        "D4_only",
                        "D5_only",
                    )
                },
                "mainWeights": weight_violations(main_b),
                "dlfRestoreDecomposition": {
                    "alone": dlf_restore_decomposition(bs["S0_all_off"], bs["DLF_restore_only"]),
                    "onTopOfCombined": dlf_restore_decomposition(
                        bs["S5_combined_hold_kept"], bs["S5_combined"]
                    ),
                },
                "crossProviderFamilyCorrection": (
                    "no correction flag: no family groups different providers on "
                    "similarity alone (see familyAudit), so 'DLF restored with the "
                    "cross-provider correction' is the DLF_restore_only build"
                ),
            }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
