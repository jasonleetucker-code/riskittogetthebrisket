#!/usr/bin/env python3
"""Owner closeout 2026-10-18, Decisions 2-5: source-independence replay.

Read-only measurement instrument for the four source-independence decisions
(``docs/sources/IDP_SOURCE_INDEPENDENCE_CLOSEOUT_2026-10-18.md``):

* **D2** — the IDP-scoped shared correlation cap (``idp_shared_correlation_cap``,
  ``data_contract.ROW_SCOPED_CORRELATION_GROUPS``);
* **D3** — the IDP Trade Calculator offense-vote exclusion
  (``idptc_offense_vote_excluded``, ``POLICY_SOURCE_ROW_CLASS_VOTE_HOLDS``);
* **D4** — DLF Values rank -> Hill (``dlf_values_rank_hill_vote``);
* **D5** — FantasyPros IDP on its vendor-stated clock (``freshness_v1.json``
  ``style: EXPLICIT_UPSTREAM_TIMESTAMP``).

Every build goes through the canonical pipeline (``src/api/value_replay.build``)
with one controlled change against a BASELINE in which all four decisions are
off.  Independent checks recompute, from each row's own per-source stamps and
a declaration written HERE (not the production map), the B11 family count and
the independence axis level, and compare them with what the pipeline stamped.

Historical archives are replayed through the contract's ``csv_root`` seam on
a temporary tree: ``CSVs/site_raw`` and ``data/scrape_state`` as committed by
the commit that added the archive, overlaid with the archive's own site_raw.
An archive older than the dataset-state store builds without freshness
weighting (the documented replay posture) and is labelled so.

Changes nothing in the repository: writes only ``--out``.  Feature flags and
the freshness-config variant are set inside one build and restored.

Usage::

    python scripts/source_independence_closeout.py \\
        --out docs/sources/evidence/SOURCE_INDEPENDENCE_2026-10-18/closeout.json

Exit codes: 0 written; 2 input missing.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import dataclasses
import hashlib
import importlib.util
import io
import json
import random
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterator, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api import data_contract as dc  # noqa: E402
from src.api import feature_flags  # noqa: E402
from src.api import value_replay as vr  # noqa: E402
from src.sources import freshness as fr  # noqa: E402

DEFAULT_PAYLOAD = REPO / "exports" / "latest" / "dynasty_data_2026-10-18.json"
ARCHIVE_DIR = REPO / "exports" / "archive"
#: Earlier complete archives replayed for D2 / D3, chosen to span the IDP
#: Show combined board's voting life (fresh in early September, decaying
#: through October) plus the pinned newest.
DEFAULT_HISTORY = (
    "dynasty_export_20260905_204615.zip",
    "dynasty_export_20260915_214858.zip",
    "dynasty_export_20260925_233646.zip",
    "dynasty_export_20261002_",
    "dynasty_export_20261010_",
    "dynasty_export_20261018_114711.zip",
)

FLAGS = {
    "D2": "idp_shared_correlation_cap",
    "D3": "idptc_offense_vote_excluded",
    "D4": "dlf_values_rank_hill_vote",
}
D5_SOURCE = "fantasyProsIdp"
_OFFENSE = {"QB", "RB", "WR", "TE"}
_IDP = {"DL", "LB", "DB"}
#: Independent restatement of the D2 rule (deliberately NOT read from
#: ``dc.ROW_SCOPED_CORRELATION_GROUPS``): on an IDP row where both vote with
#: positive weight, these two are one family.
_D2_MEMBERS = ("idpTradeCalc", "idpShowCombined")
_D2_GROUP = "idpShow"
_INDEPENDENCE_HIGH, _INDEPENDENCE_MEDIUM = 5, 3


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _q(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 3)


def _git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode()


@contextlib.contextmanager
def _freshness_style(source_key: str, style: str | None) -> Iterator[None]:
    """One build with ``source_key``'s configured publication style replaced."""
    cfg = fr.default_config()
    cadence = cfg.sources.get(source_key, cfg.default_cadence)
    variant = dataclasses.replace(
        cfg, sources={**cfg.sources, source_key: dataclasses.replace(cadence, style=style)}
    )
    saved = fr._CONFIG_CACHE.get("default")
    fr._CONFIG_CACHE["default"] = variant
    dc._SOURCE_WEIGHTING_CACHE.clear()
    try:
        yield
    finally:
        if saved is None:
            fr._CONFIG_CACHE.pop("default", None)
        else:
            fr._CONFIG_CACHE["default"] = saved
        dc._SOURCE_WEIGHTING_CACHE.clear()


def build(
    raw: Mapping[str, Any],
    *,
    on: frozenset[str],
    csv_root: Path | None = None,
) -> dict[str, Any]:
    """One canonical build with exactly the decisions in ``on`` enabled."""
    flags = [(FLAGS[d], d in on) for d in ("D2", "D3", "D4")]
    style = fr.STYLE_EXPLICIT if "D5" in on else None
    spec: dict[str, Any] = {"flags": flags}
    if csv_root is not None:
        spec["csv_root"] = csv_root
    with _freshness_style(D5_SOURCE, style):
        return vr.build(raw, spec)


# ── per-row readers ──────────────────────────────────────────────────────────


def _rows(contract: Mapping[str, Any]) -> dict[str, dict]:
    return {
        str(r.get("displayName")): r
        for r in contract.get("playersArray") or []
        if isinstance(r, dict) and r.get("displayName")
    }


def _klass(row: Mapping[str, Any]) -> str:
    pos = str(row.get("position") or "").upper()
    if row.get("assetClass") == "pick" or pos == "PICK":
        return "pick"
    return "idp" if pos in _IDP else ("offense" if pos in _OFFENSE else "other")


def _voters(row: Mapping[str, Any]) -> dict[str, dict]:
    """Sources that cast a weighted vote on the row (pre-Hampel)."""
    out = {}
    for k, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, dict):
            continue
        w = m.get("preFamilyWeight", m.get("appliedWeight"))
        if m.get("excludedReason") == "freshness_or_health_zero_weight":
            continue
        if isinstance(w, (int, float)) and w > 0:
            out[k] = m
    return out


def independent_family_check(contract: Mapping[str, Any], *, d2_on: bool) -> dict[str, Any]:
    """Recompute the independence count from the row's own stamps.

    Family of each surviving voter = the registry's declared group, with the
    D2 rule restated here.  Compared with ``independentSourceCount`` and with
    the B11 independence axis (>= 5 high, >= 3 medium, else low).  Also checks
    that every merged family carried at most one provider's authority.
    """
    fam = vr.source_families()
    mismatches: list[dict] = []
    axis_mismatch = 0
    engaged_rows: list[str] = []
    cap_violations: list[dict] = []
    checked = 0
    for name, row in _rows(contract).items():
        voters = _voters(row)
        if not voters or row.get("independentSourceCount") is None:
            continue
        klass = _klass(row)
        engaged = d2_on and klass == "idp" and all(k in voters for k in _D2_MEMBERS)
        families = dict(fam)
        if engaged:
            engaged_rows.append(name)
            for k in _D2_MEMBERS:
                families[k] = _D2_GROUP
            total = sum(
                float(voters[k].get("appliedWeight") or 0.0)
                for k in _D2_MEMBERS
                if not voters[k].get("hampelDropped")
            )
            if total > 1.0 + 1e-3:
                cap_violations.append({"row": name, "lineageWeight": round(total, 4)})
        surviving = [k for k, m in voters.items() if not m.get("hampelDropped")]
        count = len({families.get(k, k) for k in surviving})
        checked += 1
        if count != row.get("independentSourceCount"):
            mismatches.append(
                {"row": name, "recomputed": count, "stamped": row["independentSourceCount"]}
            )
        axes = row.get("confidenceAxes") or {}
        if "independence" in axes and klass != "pick":
            level = (
                "high"
                if count >= _INDEPENDENCE_HIGH
                else ("medium" if count >= _INDEPENDENCE_MEDIUM else "low")
            )
            # The axis counts families carrying a value contribution; a row
            # whose stamped count agrees but whose axis disagrees is reported.
            if axes["independence"] != level:
                axis_mismatch += 1
    stamped_engaged = sorted(n for n, r in _rows(contract).items() if r.get("sharedLineageCaps"))
    return {
        "rowsChecked": checked,
        "countMismatches": len(mismatches),
        "countMismatchExamples": mismatches[:10],
        "independenceAxisMismatches": axis_mismatch,
        "d2EngagedRowsRecomputed": len(engaged_rows),
        "d2EngagedRowsStamped": len(stamped_engaged),
        "d2EngagementAgrees": sorted(engaged_rows) == stamped_engaged,
        "d2LineageCapViolations": cap_violations[:10],
    }


def compare(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    """Value / rank / confidence movement, by asset class, alt vs base."""
    a, b = _rows(base), _rows(alt)
    by: dict[str, list[tuple[float, str, int, int]]] = {}
    newly_unpriced, newly_priced = [], []
    conf_flips: dict[str, int] = {}
    conf_dir: dict[str, int] = {}
    indep_changes: dict[str, int] = {}
    for name, ra in a.items():
        rb = b.get(name)
        if rb is None:
            continue
        va, vb = ra.get("rankDerivedValue"), rb.get("rankDerivedValue")
        klass = _klass(ra)
        if va and not vb:
            newly_unpriced.append(name)
        elif vb and not va:
            newly_priced.append(name)
        elif va and vb and va != vb:
            by.setdefault(klass, []).append((100.0 * (vb - va) / va, name, va, vb))
        ca, cb = ra.get("confidenceBucket"), rb.get("confidenceBucket")
        if ca != cb:
            conf_flips[klass] = conf_flips.get(klass, 0) + 1
            conf_dir[f"{ca}->{cb}"] = conf_dir.get(f"{ca}->{cb}", 0) + 1
        if ra.get("independentSourceCount") != rb.get("independentSourceCount"):
            indep_changes[klass] = indep_changes.get(klass, 0) + 1
    ranked_a = {n: r.get("canonicalConsensusRank") for n, r in a.items()}

    def top_max(moves, n):
        xs = [abs(m[0]) for m in moves if (ranked_a.get(m[1]) or 10**9) <= n]
        return round(max(xs), 2) if xs else 0.0

    out_classes = {}
    for klass, moves in sorted(by.items()):
        absd = [abs(m[0]) for m in moves]
        out_classes[klass] = {
            "moved": len(moves),
            "absPctP50": _q(absd, 0.5),
            "absPctP90": _q(absd, 0.9),
            "absPctMax": round(max(absd), 2),
            "top50MaxAbsPct": top_max(moves, 50),
            "top150MaxAbsPct": top_max(moves, 150),
            "largest": [
                {"name": n, "from": x, "to": y, "pct": round(p, 2)}
                for p, n, x, y in sorted(moves, key=lambda m: -abs(m[0]))[:8]
            ],
        }
    rank_changes = sum(
        1
        for n, ra in a.items()
        if n in b and ra.get("canonicalConsensusRank") != b[n].get("canonicalConsensusRank")
    )
    top = lambda rows, n: {  # noqa: E731
        k for k, r in rows.items() if (r.get("canonicalConsensusRank") or 10**9) <= n
    }
    return {
        "boardHashBase": vr.board_hash(base),
        "boardHashAlt": vr.board_hash(alt),
        "valuesMoved": sum(len(m) for m in by.values()),
        "byClass": out_classes,
        "newlyUnpriced": newly_unpriced,
        "newlyPriced": newly_priced,
        "rankChanges": rank_changes,
        "top50MembershipSwaps": len(top(a, 50) - top(b, 50)),
        "top200MembershipSwaps": len(top(a, 200) - top(b, 200)),
        "confidenceBucketFlipsByClass": conf_flips,
        "confidenceBucketDirections": conf_dir,
        "independentSourceCountChangesByClass": indep_changes,
    }


def policy_stamp(contract: Mapping[str, Any]) -> Any:
    return ((contract.get("sourceWeighting") or {}) or {}).get("independencePolicy")


# ── D3 ──────────────────────────────────────────────────────────────────────


def d3_checks(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    a, b = _rows(base), _rows(alt)
    offense_votes_before = offense_votes_after = 0
    other_changed: list[str] = []
    only_source_offense = 0
    for name, ra in a.items():
        rb = b.get(name, {})
        ma = (ra.get("sourceRankMeta") or {}).get("idpTradeCalc")
        mb = (rb.get("sourceRankMeta") or {}).get("idpTradeCalc")
        if _klass(ra) == "offense":
            offense_votes_before += bool(ma)
            offense_votes_after += bool(mb)
            if ma and set(_voters(ra)) == {"idpTradeCalc"}:
                only_source_offense += 1
        elif ma or mb:
            keys = ("rawRank", "valueContribution", "appliedWeight", "preFamilyWeight")
            if not ma or not mb or any(ma.get(k) != mb.get(k) for k in keys):
                other_changed.append(name)
    return {
        "idpTradeCalcOffenseVotesBefore": offense_votes_before,
        "idpTradeCalcOffenseVotesAfter": offense_votes_after,
        "offenseRowsWhereItWasTheOnlyVoter": only_source_offense,
        "idpAndPickVotesChanged": len(other_changed),
        "idpAndPickVotesChangedExamples": other_changed[:10],
    }


# ── D4 ──────────────────────────────────────────────────────────────────────


def d4_checks(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    key = "dlfValuesSfTep"
    a, b = _rows(base), _rows(alt)
    votes_by_class: dict[str, int] = {}
    dropped = 0
    fam_total_max = 0.0
    indep_up: list[str] = []
    indep_up_dlf_present: list[str] = []
    pick_moves_non_tether: list[str] = []
    idp_moves: list[str] = []
    for name, rb in b.items():
        ra = a.get(name, {})
        m = (rb.get("sourceRankMeta") or {}).get(key)
        if m:
            votes_by_class[_klass(rb)] = votes_by_class.get(_klass(rb), 0) + 1
            dropped += bool(m.get("hampelDropped"))
        dlf_total = sum(
            float(mm.get("appliedWeight") or 0.0)
            for kk, mm in (rb.get("sourceRankMeta") or {}).items()
            if isinstance(mm, dict)
            and kk.startswith("dlf")
            and not mm.get("hampelDropped")
            and mm.get("contributedToBlend", True) is not False
        )
        fam_total_max = max(fam_total_max, dlf_total)
        # DLF Values may give the ONE dlf family coverage on a row DLF Rank
        # does not reach; it must never add a family where DLF already voted.
        ia, ib = ra.get("independentSourceCount"), rb.get("independentSourceCount")
        dlf_before = any(
            k.startswith("dlf") and not mm.get("hampelDropped") for k, mm in _voters(ra).items()
        )
        if isinstance(ia, int) and isinstance(ib, int) and ib > ia:
            if not dlf_before:
                indep_up.append(name)
            else:
                fam = vr.source_families()

                def fams(row):
                    return {
                        fam.get(k, k)
                        for k, mm in _voters(row).items()
                        if not mm.get("hampelDropped")
                    }

                indep_up_dlf_present.append(
                    {"row": name, "familiesAdded": sorted(fams(rb) - fams(ra))}
                )
        va, vb = ra.get("rankDerivedValue"), rb.get("rankDerivedValue")
        if va != vb:
            if _klass(rb) == "idp":
                idp_moves.append(name)
            elif _klass(rb) == "pick":
                # A current-year slot pick inherits the rookie pool's value
                # (the tether) and a tier alias follows its slot: both are the
                # documented coupling, not a DLF Values vote on a pick.
                prov = rb.get("pickValueProvenance") or {}
                if prov.get("class") not in ("rookie_pool_tether", "alias_suppressed"):
                    pick_moves_non_tether.append(name)
    votes = sum(votes_by_class.values())
    second_dlf = [r for r in indep_up_dlf_present if "dlf" in r["familiesAdded"]]
    return {
        # Where DLF already voted, a rise can only come from the incumbent
        # outlier filter re-judging ANOTHER family on the larger panel; a
        # second DLF family would be a double count and must be empty.
        "rowsWhereASecondDlfFamilyWasCounted": second_dlf,
        "votesByClass": votes_by_class,
        "hampelDropRate": round(dropped / votes, 4) if votes else None,
        "maxDlfFamilyAppliedWeight": round(fam_total_max, 4),
        "rowsWhereDlfFamilyGainedCoverage": len(indep_up),
        "rowsWhereDlfFamilyGainedCoverageExamples": indep_up[:10],
        "rowsWhereCountRoseThoughDlfAlreadyVoted": indep_up_dlf_present,
        "idpValueMoves": idp_moves,
        "pickValueMovesNotRookieTether": pick_moves_non_tether,
    }


def dlf_values_capture(contract: Mapping[str, Any]) -> dict[str, Any]:
    import csv

    path = REPO / "CSVs" / "site_raw" / "dlfValuesSfTep.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    vals = [float(r["value"]) for r in rows if r.get("value")]
    pos: dict[str, int] = {}
    for r in rows:
        pos[r.get("pos") or ""] = pos.get(r.get("pos") or "", 0) + 1
    sw = ((contract.get("sourceWeighting") or {}).get("sources") or {}).get("dlfValuesSfTep") or {}
    sub = (sw.get("subsets") or {}).get("players") or {}
    return {
        "csvSha256": _sha256(path),
        "rows": len(rows),
        "byPosition": pos,
        "nonPositiveValues": sum(1 for v in vals if v <= 0),
        "distinctValues": len(set(vals)),
        "pickRowsInVotingCsv": sum(1 for r in rows if str(r.get("name", "")).strip()[:4].isdigit()),
        "freshness": {
            k: sub.get(k)
            for k in (
                "publicationStyle",
                "freshnessClock",
                "sourceDataAsOf",
                "ageHours",
                "expectedCadenceHours",
                "freshness",
                "state",
            )
        },
        "health": sw.get("health"),
    }


def package_model_check(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    """The ACTIVE package model over a fixed, seeded grid of package pairings.

    Same asset names both sides; only the board values differ.  Reports the
    model's invariants on both boards (non-negative adjustment, adjusted >=
    raw) and how many pairings change side or cross the 250-point even band.
    """
    from src.valuation_math import package_model as pm

    a, b = _rows(base), _rows(alt)
    pool = sorted(
        (n for n, r in a.items() if _klass(r) == "offense" and r.get("rankDerivedValue")),
        key=lambda n: -a[n]["rankDerivedValue"],
    )[:200]
    pool = [n for n in pool if (b.get(n) or {}).get("rankDerivedValue")]
    rng = random.Random(20261018)
    shapes = ((1, 2), (2, 3), (1, 3), (2, 2))
    flips = band = invariant_failures = total = 0
    rel_gap_change: list[float] = []
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
            res.append((la + ra_) / 2.0)
        total += 1
        g0, m0, g1, m1 = res
        if (g0 > 0) != (g1 > 0) and g0 != 0 and g1 != 0:
            flips += 1
        if (abs(g0) <= 250) != (abs(g1) <= 250):
            band += 1
        rel_gap_change.append(abs(g1 / m1 - g0 / m0) * 100.0)
    return {
        "activeModel": pm.active_model_id(),
        "pairings": total,
        "invariantFailures": invariant_failures,
        "sideFlips": flips,
        "even250BandCrossings": band,
        "relativeGapChangePctP50": _q(rel_gap_change, 0.5),
        "relativeGapChangePctP90": _q(rel_gap_change, 0.9),
    }


# ── D5 ──────────────────────────────────────────────────────────────────────


def d5_checks(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    import csv

    def sub(contract):
        s = ((contract.get("sourceWeighting") or {}).get("sources") or {}).get(D5_SOURCE) or {}
        p = (s.get("subsets") or {}).get("players") or {}
        keep = (
            "publicationStyle",
            "freshnessClock",
            "sourceDataAsOf",
            "lastBroadDatasetChangeAt",
            "ageHours",
            "expectedCadenceHours",
            "freshness",
            "state",
        )
        return {
            **{k: p.get(k) for k in keep},
            "votingRows": s.get("votingRows"),
            "excludedRows": s.get("excludedRows"),
        }

    path = REPO / "CSVs" / "site_raw" / f"{D5_SOURCE}.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)
    dups = {n: rs for n, rs in by_name.items() if len(rs) > 1}
    board = _rows(alt)
    dup_votes = []
    for n, rs in sorted(dups.items()):
        m = ((board.get(n) or {}).get("sourceRankMeta") or {}).get(D5_SOURCE)
        dup_votes.append(
            {
                "name": n,
                "csvEntries": [
                    {"family": r.get("family"), "effectiveRank": int(r["effectiveRank"])}
                    for r in rs
                ],
                "votesOnBoard": 1 if m else 0,
                "votedRawRank": (m or {}).get("rawRank"),
            }
        )
    # Ranks are computed over BOARD rows (one per player), so a duplicate CSV
    # entry cannot occupy a second position in the source's ordinal pool.
    ranked = sorted(
        (
            (m["rawRank"], n)
            for n, r in board.items()
            for m in [((r.get("sourceRankMeta") or {}).get(D5_SOURCE))]
            if isinstance(m, dict) and m.get("rawRank")
        )
    )
    names_ranked = [n for _rk, n in ranked]
    return {
        "before": sub(base),
        "after": sub(alt),
        "upstreamStateFile": "data/scrape_state/fantasyProsIdp_upstream.json",
        "csvRows": len(rows),
        "csvDuplicateIdentities": len(dups),
        "duplicateVotes": dup_votes,
        "everyDuplicateVotesAtMostOnce": all(d["votesOnBoard"] <= 1 for d in dup_votes),
        "boardRowsWithAFantasyProsIdpVote": len(names_ranked),
        "distinctNamesAmongThoseVotes": len(set(names_ranked)),
    }


# ── history ─────────────────────────────────────────────────────────────────


def _archive_add_commit(name: str) -> str | None:
    out = _git("log", "--diff-filter=A", "--format=%H", "--", f"exports/archive/{name}")
    lines = [line for line in out.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _resolve_archive(prefix: str) -> Path | None:
    hits = sorted(ARCHIVE_DIR.glob(prefix if prefix.endswith(".zip") else prefix + "*.zip"))
    return hits[-1] if hits else None


def historical(prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for prefix in prefixes:
        path = _resolve_archive(prefix)
        if path is None:
            out.append({"archive": prefix, "skipped": "not found"})
            continue
        commit = _archive_add_commit(path.name)
        if commit is None:
            out.append({"archive": path.name, "skipped": "no commit adds it"})
            continue
        with zipfile.ZipFile(path) as zf:
            names = sorted(
                n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            raw = json.loads(zf.read(names[-1]))
            site = {
                Path(n).name: zf.read(n)
                for n in zf.namelist()
                if n.startswith("site_raw/") and n.endswith(".csv")
            }
        with tempfile.TemporaryDirectory(prefix="sic-") as tmp:
            root = Path(tmp)
            tree = _git("archive", commit, "CSVs/site_raw", "data/scrape_state", binary=True)
            with tarfile.open(fileobj=io.BytesIO(tree)) as tar:
                tar.extractall(root, filter="data")  # noqa: S202 -- our own repository
            target = root / "CSVs" / "site_raw"
            for name, blob in site.items():
                (target / name).write_bytes(blob)
            has_state = any((root / "data" / "scrape_state").glob("*_dataset.json"))
            base = build(raw, on=frozenset(), csv_root=root)
            d2 = build(raw, on=frozenset({"D2"}), csv_root=root)
            d3 = build(raw, on=frozenset({"D3"}), csv_root=root)
        show_votes = sum(
            1
            for r in _rows(base).values()
            if _klass(r) == "idp" and "idpShowCombined" in _voters(r)
        )
        both = sum(
            1
            for r in _rows(base).values()
            if _klass(r) == "idp" and all(k in _voters(r) for k in _D2_MEMBERS)
        )
        out.append(
            {
                "archive": path.name,
                "archiveSha256": _sha256(path),
                "csvCommit": commit,
                "datasetStatePresent": has_state,
                "scrapeTimestamp": raw.get("scrapeTimestamp"),
                "idpRowsWhereIdpShowCombinedVotes": show_votes,
                "idpRowsWhereBothD2MembersVote": both,
                "d2": {
                    "diff": compare(base, d2),
                    "independentCheck": independent_family_check(d2, d2_on=True),
                    "policy": policy_stamp(d2),
                },
                "d3": {"diff": compare(base, d3), "checks": d3_checks(base, d3)},
                "baselineIndependentCheck": independent_family_check(base, d2_on=False),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-history", action="store_true")
    args = ap.parse_args(argv)
    if not args.payload.exists():
        print(f"error: payload not found: {args.payload}", file=sys.stderr)
        return 2
    raw = json.loads(args.payload.read_text(encoding="utf-8"))
    builds = {
        "baseline": build(raw, on=frozenset()),
        "D2": build(raw, on=frozenset({"D2"})),
        "D3": build(raw, on=frozenset({"D3"})),
        "D4": build(raw, on=frozenset({"D4"})),
        "D5": build(raw, on=frozenset({"D5"})),
    }
    defaults = vr.build(copy.deepcopy(raw))
    base = builds["baseline"]
    spec = importlib.util.spec_from_file_location(
        "idp_rehab_eval", REPO / "scripts/idp_rehab_eval.py"
    )
    rehab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehab)
    report: dict[str, Any] = {
        "schema": "source-independence-closeout/v1",
        "pins": {
            "code": vr._git("rev-parse", "HEAD"),
            "workingTreeDirty": vr._dirty(),
            "payload": str(args.payload.relative_to(REPO)),
            "payloadSha256": _sha256(args.payload),
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
            "flagDefaults": {flag: feature_flags._DEFAULTS[flag] for flag in FLAGS.values()},
            "boardHashes": {k: vr.board_hash(v) for k, v in builds.items()}
            | {"productionDefaults": vr.board_hash(defaults)},
        },
        "baselineIndependentCheck": independent_family_check(base, d2_on=False),
        "D2": {
            "diff": compare(base, builds["D2"]),
            "independentCheck": independent_family_check(builds["D2"], d2_on=True),
            "policy": policy_stamp(builds["D2"]),
        },
        "D3": {
            "diff": compare(base, builds["D3"]),
            "checks": d3_checks(base, builds["D3"]),
            "independentCheck": independent_family_check(builds["D3"], d2_on=False),
            "packageModel": package_model_check(base, builds["D3"]),
            "policy": policy_stamp(builds["D3"]),
        },
        "D4": {
            "diff": compare(base, builds["D4"]),
            "checks": d4_checks(base, builds["D4"]),
            "capture": dlf_values_capture(builds["D4"]),
            "publicationHistory": rehab.dlf_values_publication_history(),
            "independentCheck": independent_family_check(builds["D4"], d2_on=False),
            "packageModel": package_model_check(base, builds["D4"]),
        },
        "D5": {
            "diff": compare(base, builds["D5"]),
            "checks": d5_checks(base, builds["D5"]),
        },
        "productionDefaults": {
            "diff": compare(base, defaults),
            "independentCheck": independent_family_check(defaults, d2_on=True),
            "packageModel": package_model_check(base, defaults),
            "policy": policy_stamp(defaults),
        },
    }
    if not args.no_history:
        report["history"] = historical(DEFAULT_HISTORY)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
