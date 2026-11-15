#!/usr/bin/env python3
"""Directive §9 / prereg §15: DLF IDP, DLF Rookie IDP (and D4) restoration readiness.

Run with cwd = a throwaway tree of the V2 code commit whose ``CSVs/`` and ``data/``
are pinned to the input commit (``../rootcause/pin_inputs.sh``)::

    python oiv2_dlf_readiness.py PAYLOAD.json TAG OUT_DIR

Builds, on ONE frozen payload + CSVs + data + weights + configuration, the boards
of prereg §6.1 that the activation question needs (only the two DLF flags, the
per-row filter and, for the two stress boards, one documented source override
differ), runs the §9 readiness checks R1-R10 on them, and writes:

* ``READINESS_<tag>.md`` -- every check with its numbers and verdict;
* ``IMPACT_<tag>.md``    -- the activation impact summary per scenario;
* ``impact_<tag>.csv``   -- the exact per-row impact (every row whose value, rank
  or confidence bucket changes, in every scenario), with source-level attribution;
* ``readiness_<tag>.json`` -- everything machine-readable.

Read-only: no code path, flag default, constant, weight or value is changed. The
flags are set inside this process only, one board at a time
(``value_replay._flag``), exactly as ``oiv2_gates.build`` does.
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import io
import json
import re
import resource
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from src.api import data_contract as dc  # noqa: E402
from src.api import source_integrity as si  # noqa: E402
from src.api import value_replay as vr  # noqa: E402
from src.robust_filter_shadow import oiv2_gates as G  # noqa: E402
from src.trade import finder as trade_finder  # noqa: E402
from src.trade import suggestions as trade_suggestions  # noqa: E402

DLF_IDP = ("dlfIdp", "dlfRookieIdp")
DLF_ALL = ("dlfSf", "dlfRookieSf", "dlfIdp", "dlfRookieIdp", "dlfValuesSfTep")
OTHER_IDP = ("draftSharksIdp", "fantasyProsIdp", "idpTradeCalc")
IDP_POS = {"DL", "LB", "DB"}

# name: (filter, DLF IDP held (dlf_offense_only_vote), D4 on, source overrides)
BOARDS: dict[str, tuple[str, bool, bool, dict | None]] = {
    "A": ("incumbent", True, False, None),  # production today
    "B": ("incumbent", False, False, None),  # the defect (DLF IDP + incumbent)
    "D": ("v2", True, False, None),  # V2 alone
    "C": ("v2", False, False, None),  # V2 + DLF IDP / DLF Rookie IDP
    "C'": ("v2", True, True, None),  # V2 + D4
    "C''": ("v2", False, True, None),  # V2 + DLF IDP + D4
    # stress: the rookie-ladder reference (and IDP shared-market backbone) off
    # through the documented user source-override path (prereg S11 shape)
    "C_noIDPTC": ("v2", False, False, {"idpTradeCalc": {"include": False}}),
    "B_noIDPTC": ("incumbent", False, False, {"idpTradeCalc": {"include": False}}),
}

SCENARIOS = (
    # (id, label, base, target)
    ("S1", "V2 only (DLF IDP held, D4 off)", "A", "D"),
    ("S2", "V2 + DLF IDP + DLF Rookie IDP (§9 primary target)", "A", "C"),
    ("S3", "V2 + D4 (DLF IDP held)", "A", "C'"),
    ("S4", "V2 + DLF IDP + DLF Rookie IDP + D4 (everything)", "A", "C''"),
    ("I1", "increment: DLF IDP given V2", "D", "C"),
    ("I2", "increment: D4 given V2", "D", "C'"),
    ("I3", "increment: D4 given V2 + DLF IDP", "C", "C''"),
    ("I4", "increment: DLF IDP given V2 + D4", "C'", "C''"),
)

TWO_WAY = "Travis Hunter"
TRADE_SAMPLES = (
    # (label, side A names, side B names) -- illustrative packages built from the
    # owner-named / most-moved IDP rows; the point is the single downstream path
    ("1-for-2 edge rushers", ["Myles Garrett"], ["T.J. Watt", "Danielle Hunter"]),
    ("rookie LB for vet LB", ["Jacob Rodriguez"], ["Trevin Wallace"]),
    ("2-for-1 IDP stars", ["Aidan Hutchinson", "Will Anderson"], ["Jared Verse"]),
)


def log(msg: str) -> None:
    print(f"[dlf-readiness] {msg}", file=sys.stderr, flush=True)


# ── building ───────────────────────────────────────────────────────────


def build(name: str, raw: dict) -> dict:
    config, held, d4, overrides = BOARDS[name]
    flags = G._flags_for(config, {"dlf_offense_only_vote": held, "dlf_values_rank_hill_vote": d4})
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
        for flag, enabled in sorted(flags.items()):
            stack.enter_context(vr._flag(flag, enabled))
        if config == "v2":
            stack.enter_context(si.history_override(None))  # NO-HISTORY
        return dc.build_api_data_contract(
            json.loads(json.dumps(raw)),
            source_overrides=json.loads(json.dumps(overrides)) if overrides else None,
            csv_root=None,
        )


# ── reading a board ────────────────────────────────────────────────────


def rkey(r: dict, seen: set) -> str:
    n = str(r.get("displayName") or "")
    k = n
    i = 2
    while k in seen:
        k = f"{n}|{r.get('position')}|{r.get('assetClass')}#{i}"
        i += 1
    seen.add(k)
    return k


def val(r: dict | None) -> int | None:
    v = (r or {}).get("rankDerivedValue")
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


def status(r: dict, s: str) -> str | None:
    return G.exclusion_of(r, s)


def integ_reason(r: dict, s: str) -> str | None:
    m = (r.get("sourceRankMeta") or {}).get(s) or {}
    integ = m.get("integrity")
    if isinstance(integ, dict):
        return integ.get("primaryReason")
    return None


def voting(r: dict) -> dict[str, dict]:
    out = {}
    for s, m in (r.get("sourceRankMeta") or {}).items():
        if isinstance(m, dict) and status(r, s) is None and (m.get("appliedWeight") or 0) > 0:
            out[s] = m
    return out


def compact(c: dict) -> dict[str, dict]:
    seen: set = set()
    rows = {}
    for r in c.get("playersArray") or []:
        rows[rkey(r, seen)] = r
    return rows


# ── checks ─────────────────────────────────────────────────────────────


def check_family_cap(rows: dict[str, dict]) -> dict:
    """R1: every DLF member votes inside the ONE ``dlf`` family cap."""
    groups = {s: dc.correlation_group_for(s) for s in DLF_ALL}
    providers = {s: si_provider(s) for s in DLF_ALL}
    multi = []
    violations = []
    family_count_mismatch = []
    for k, r in rows.items():
        v = voting(r)
        members = {s: m for s, m in v.items() if groups.get(s) == "dlf" or s in DLF_ALL}
        if members:
            base = max(float(m.get("baseWeight") or 1.0) for m in members.values())
            total = sum(float(m.get("appliedWeight") or 0.0) for m in members.values())
            if total > base + 1e-3:
                violations.append({"row": k, "total": round(total, 4), "cap": base})
            if len(members) >= 2:
                multi.append(
                    {
                        "row": k,
                        "members": {
                            s: {
                                "appliedWeight": m.get("appliedWeight"),
                                "familyAdjustment": m.get("familyAdjustment"),
                                "preFamilyWeight": m.get("preFamilyWeight"),
                                "value": m.get("valueContribution"),
                            }
                            for s, m in sorted(members.items())
                        },
                        "familyTotal": round(total, 4),
                    }
                )
        fams = {dc.correlation_group_for(s) for s in v}
        isc = r.get("independentSourceCount")
        if v and isinstance(isc, int) and isc != len(fams):
            family_count_mismatch.append(
                {"row": k, "independentSourceCount": isc, "families": len(fams)}
            )
    combos = Counter(tuple(sorted(x["members"])) for x in multi)
    return {
        "correlationGroups": groups,
        "providers": providers,
        "rowsWithTwoOrMoreDlfMembers": len(multi),
        "memberCombinations": {"+".join(k): n for k, n in sorted(combos.items())},
        "capViolations": violations,
        "independentCountMismatches": family_count_mismatch[:50],
        "independentCountMismatchCount": len(family_count_mismatch),
        "examples": multi[:8],
        "pass": not violations
        and not family_count_mismatch
        and len(set(groups.values())) == 1
        and len(set(providers.values())) == 1,
    }


def si_provider(s: str) -> str:
    try:
        return str(dc._integrity_provider_of(s))
    except Exception:  # noqa: BLE001
        return "?"


def read_csv_names(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


_DLF_POS = {"DE": "DL", "DT": "DL", "EDGE": "DL", "DL": "DL", "LB": "LB", "ILB": "LB", "OLB": "LB"}
_DLF_POS.update({"CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB"})


def check_populations(rows: dict[str, dict], held_rows: dict[str, dict]) -> dict:
    """R2: who DLF IDP / DLF Rookie IDP vote on (and that the hold really holds)."""
    out: dict[str, Any] = {}
    raw_pos = {}
    for e in read_csv_names(ROOT / "CSVs" / "dlf_idp.csv"):
        m = re.match(r"\s*([A-Z]+)", str(e.get("Pos") or ""))
        if m:
            raw_pos[dc._canonical_match_key(str(e.get("Name") or ""))] = _DLF_POS.get(m.group(1))
    for s in DLF_IDP:
        csv_rows = read_csv_names(ROOT / "CSVs" / "site_raw" / f"{s}.csv")
        present = {}
        for k, r in rows.items():
            if s in (r.get("sourceRankMeta") or {}):
                present[k] = r
        vote_rows = {k: r for k, r in present.items() if status(r, s) is None}
        cls = Counter(str(r.get("assetClass")) for r in vote_rows.values())
        pos = Counter(str(r.get("position")) for r in vote_rows.values())
        rookie = Counter(bool(r.get("rookie")) for r in vote_rows.values())
        refused = []
        for k, r in rows.items():
            integ = (r.get("sourceIntegrity") or {}).get(s) or {}
            ident = integ.get("identity") or {}
            if ident.get("verdict") not in (None, "VERIFIED", "NAME_ONLY"):
                refused.append(
                    {"row": k, "verdict": ident.get("verdict"), "reason": ident.get("reason")}
                )
        matched_names = set()
        for r in present.values():
            nm = (r.get("sourceRankMeta") or {}).get(s, {}).get("matchedName") or r.get(
                "displayName"
            )
            matched_names.add(dc._canonical_match_key(str(nm)))
        unmatched = [
            e.get("name")
            for e in csv_rows
            if dc._canonical_match_key(str(e.get("name") or "")) not in matched_names
            and not any(
                dc._canonical_match_key(str(e.get("name") or ""))
                == dc._canonical_match_key(str(r.get("displayName") or ""))
                for r in present.values()
            )
        ]
        pos_mismatch = []
        if s == "dlfIdp":
            for k, r in vote_rows.items():
                p = raw_pos.get(dc._canonical_match_key(str(r.get("displayName") or "")))
                if p and p != str(r.get("position")):
                    pos_mismatch.append({"row": k, "dlfPos": p, "rowPos": r.get("position")})
        held_votes = sum(
            1
            for r in held_rows.values()
            if s in (r.get("sourceRankMeta") or {}) and status(r, s) is None
        )
        held_reasons = Counter(
            str(status(r, s)) for r in held_rows.values() if s in (r.get("sourceRankMeta") or {})
        )
        out[s] = {
            "csvEntries": len(csv_rows),
            "observationsOnBoard": len(present),
            "votingRows": len(vote_rows),
            "byAssetClass": dict(cls),
            "byPosition": dict(sorted(pos.items())),
            "byRookie": {str(k): n for k, n in rookie.items()},
            "csvEntriesWithoutObservation": unmatched,
            "layerARefusals": refused,
            "positionVsDlfRawExport": pos_mismatch,
            "votesOnHeldBoardA": held_votes,
            "heldBoardAStatuses": dict(held_reasons),
        }
    both = [k for k, r in rows.items() if all(s in voting(r) for s in DLF_IDP)]
    out["rowsWithBothDlfIdpBoards"] = both
    dlfidp = out["dlfIdp"]
    rook = out["dlfRookieIdp"]
    out["pass"] = (
        set(dlfidp["byAssetClass"]) <= {"idp"}
        and set(rook["byAssetClass"]) <= {"idp"}
        and set(dlfidp["byPosition"]) <= IDP_POS
        and set(rook["byPosition"]) <= IDP_POS
        and rook["byRookie"].get("False", 0) == 0
        and dlfidp["votesOnHeldBoardA"] == 0
        and rook["votesOnHeldBoardA"] == 0
        and not dlfidp["positionVsDlfRawExport"]
    )
    out["registryNote"] = {
        "dlfIdp.excludes_rookies": next(
            (s.get("excludes_rookies") for s in dc._RANKING_SOURCES if s.get("key") == "dlfIdp"),
            None,
        ),
        "dlfIdpVotesOnRookieRows": dlfidp["byRookie"].get("True", 0),
    }
    return out


def check_rookie_translation(
    rows: dict[str, dict], stress: dict[str, dict], stress_inc: dict[str, dict]
) -> dict:
    """R3: DLF Rookie IDP votes only through its IDPTC rookie ladder (fail closed)."""
    ladder = sorted(
        int(r["sourceRankMeta"]["idpTradeCalc"]["effectiveRank"])
        for r in rows.values()
        if r.get("rookie")
        and str(r.get("position") or "").upper() in IDP_POS
        and isinstance(
            ((r.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}).get("effectiveRank"),
            (int, float),
        )
    )
    entries = []
    for k, r in rows.items():
        m = (r.get("sourceRankMeta") or {}).get("dlfRookieIdp")
        if not isinstance(m, dict):
            continue
        raw_rank = m.get("rawRank")
        eff = m.get("effectiveRank")
        expected = None
        if isinstance(raw_rank, (int, float)) and ladder:
            rr = int(raw_rank)
            if 1 <= rr <= len(ladder):
                expected = ladder[rr - 1]
            else:
                tail = min(10, len(ladder))
                slope = (
                    1.0
                    if tail < 2
                    else max(1.0, (ladder[-1] - ladder[len(ladder) - tail]) / (tail - 1))
                )
                expected = max(1, ladder[-1] + int(round((rr - len(ladder)) * slope)))
        idptc = ((r.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}).get("valueContribution")
        entries.append(
            {
                "row": k,
                "rawRank": raw_rank,
                "effectiveRank": eff,
                "ladderExpected": expected,
                "method": m.get("method"),
                "vote": m.get("valueContribution"),
                "idptcOwnVote": idptc,
                "status": status(r, "dlfRookieIdp"),
            }
        )
    entries.sort(key=lambda e: (e["rawRank"] or 999))
    mism = [e for e in entries if e["effectiveRank"] != e["ladderExpected"]]
    bad_method = [e for e in entries if e["method"] != "rookie_ladder_translation_via_idpTradeCalc"]
    order_ok = all(
        (a["effectiveRank"] or 0) <= (b["effectiveRank"] or 0)
        for a, b in zip(entries, entries[1:])
        if a["rawRank"] != b["rawRank"]
    )

    def _stress(rows_x: dict[str, dict]) -> dict:
        res: dict[str, Any] = {}
        for s in DLF_IDP:
            st = Counter()
            methods = Counter()
            for r in rows_x.values():
                m = (r.get("sourceRankMeta") or {}).get(s)
                if not isinstance(m, dict):
                    continue
                st[str(status(r, s) or "voting")] += 1
                methods[str(m.get("method"))] += 1
            res[s] = {"statuses": dict(st), "methods": dict(methods)}
        # rookie rows whose dlfRookieIdp vote is an untranslated within-class rank
        top = []
        for k, r in rows_x.items():
            m = (r.get("sourceRankMeta") or {}).get("dlfRookieIdp")
            if isinstance(m, dict) and m.get("rawRank") in (1, 2, 3):
                top.append(
                    {
                        "row": k,
                        "rawRank": m.get("rawRank"),
                        "effectiveRank": m.get("effectiveRank"),
                        "vote": m.get("valueContribution"),
                        "status": status(r, "dlfRookieIdp"),
                        "rowValue": val(r),
                    }
                )
        res["dlfRookieIdpTop3"] = sorted(top, key=lambda e: e["rawRank"])
        # dlfIdp: still translated onto the shared market without IDPTC?
        ratios = []
        smt = Counter()
        for k, r in rows_x.items():
            m = (r.get("sourceRankMeta") or {}).get("dlfIdp")
            m0 = ((rows.get(k) or {}).get("sourceRankMeta") or {}).get("dlfIdp")
            if not isinstance(m, dict):
                continue
            smt[str(bool(m.get("sharedMarketTranslated")))] += 1
            if isinstance(m0, dict) and m.get("effectiveRank") and m0.get("effectiveRank"):
                ratios.append(float(m["effectiveRank"]) / float(m0["effectiveRank"]))
        res["dlfIdpSharedMarketTranslated"] = dict(smt)
        res["dlfIdpEffectiveRankRatioVsC"] = {
            "n": len(ratios),
            "median": round(statistics.median(ratios), 3) if ratios else None,
            "min": round(min(ratios), 3) if ratios else None,
            "max": round(max(ratios), 3) if ratios else None,
        }
        return res

    st_v2 = _stress(stress)
    st_inc = _stress(stress_inc)
    rookie_fc = st_v2["dlfRookieIdp"]["statuses"]
    return {
        "ladderReference": "idpTradeCalc",
        "ladderDepth": len(ladder),
        "ladder": ladder,
        "entries": entries,
        "effectiveRankMismatches": mism,
        "wrongMethod": bad_method,
        "orderPreserved": order_ok,
        "stressV2_noIDPTC": st_v2,
        "stressIncumbent_noIDPTC": st_inc,
        "pass": not mism
        and not bad_method
        and order_ok
        and set(rookie_fc) <= {si.REASON_UNTRANSLATED},
    }


def check_d4(rows_cpp: dict[str, dict], rows_c: dict[str, dict], rows_a: dict[str, dict]) -> dict:
    """R10 (D4 addendum): DLF Values (``dlfValuesSfTep``) under V2 on board C''."""
    s_key = "dlfValuesSfTep"
    present = {k: r for k, r in rows_cpp.items() if s_key in (r.get("sourceRankMeta") or {})}
    vote_rows = {k: r for k, r in present.items() if status(r, s_key) is None}
    reasons = Counter(
        str(integ_reason(r, s_key) or status(r, s_key) or "voting") for r in present.values()
    )
    not_voting = [
        {
            "row": k,
            "status": status(r, s_key),
            "vote": r["sourceRankMeta"][s_key].get("valueContribution"),
        }
        for k, r in present.items()
        if status(r, s_key) is not None
    ]
    refused = []
    for k, r in rows_cpp.items():
        ident = ((r.get("sourceIntegrity") or {}).get(s_key) or {}).get("identity") or {}
        if ident.get("verdict") not in (None, "VERIFIED", "NAME_ONLY"):
            refused.append(
                {"row": k, "verdict": ident.get("verdict"), "reason": ident.get("reason")}
            )

    def _votes(rows):
        return sum(1 for r in rows.values() if s_key in voting(r))

    cls = Counter(str(r.get("assetClass")) for r in vote_rows.values())
    pos = Counter(str(r.get("position")) for r in vote_rows.values())
    picks_vote = sum(1 for r in rows_cpp.values() if "dlfValuesSfTepPicks" in voting(r))
    return {
        "votingRows": len(vote_rows),
        "byAssetClass": dict(cls),
        "byPosition": dict(sorted(pos.items())),
        "reasons": dict(reasons),
        "notVoting": not_voting,
        "layerARefusals": refused,
        "votesOnBoardA": _votes(rows_a),
        "votesOnBoardC": _votes(rows_c),
        "dlfValuesPicksVotes": picks_vote,
        "pass": set(cls) <= {"offense"}
        and _votes(rows_a) == 0
        and _votes(rows_c) == 0
        and picks_vote == 0
        and not any(x["status"] == "filter_dropped" for x in not_voting),
    }


def check_dlf_not_rejected(rows: dict[str, dict], rows_b: dict[str, dict]) -> dict:
    """R4: DLF's own IDP votes are not rejected as outliers under V2."""
    out: dict[str, Any] = {}
    for s in DLF_IDP:
        reasons = Counter()
        dissent = []
        excluded = []
        for k, r in rows.items():
            if s not in (r.get("sourceRankMeta") or {}):
                continue
            st = status(r, s)
            reasons[str(integ_reason(r, s) or st or "voting")] += 1
            if st is not None:
                excluded.append({"row": k, "status": st})
            m = r["sourceRankMeta"][s]
            lc = (
                (m.get("integrity") or {}).get("layerC")
                if isinstance(m.get("integrity"), dict)
                else None
            )
            if integ_reason(r, s) == "kept_dissent":
                dissent.append(
                    {"row": k, "vote": m.get("valueContribution"), "rowValue": val(r), "layerC": lc}
                )
        inc_drops = [
            {
                "row": k,
                "vote": r["sourceRankMeta"][s].get("valueContribution"),
                "status": status(r, s),
            }
            for k, r in rows_b.items()
            if s in (r.get("sourceRankMeta") or {}) and status(r, s) == "filter_dropped"
        ]
        out[s] = {
            "reasonsV2": dict(reasons),
            "excludedV2": excluded,
            "keptDissentV2": dissent,
            "incumbentDropsBoardB": inc_drops,
        }
    out["pass"] = all(not out[s]["excludedV2"] for s in DLF_IDP)
    return out


def check_others_keep_voting(rows_base: dict, rows_x: dict, label: str) -> dict:
    """R5: DS / FP / IDPTC keep voting when valid (status changes on IDP rows)."""
    changes = []
    for k, r in rows_x.items():
        if r.get("assetClass") != "idp":
            continue
        b = rows_base.get(k)
        if not b:
            continue
        for s in sorted(
            set((r.get("sourceRankMeta") or {})) | set((b.get("sourceRankMeta") or {}))
        ):
            if s in DLF_IDP:
                continue
            sb, sx = status(b, s), status(r, s)
            if sb != sx:
                changes.append(
                    {"row": k, "source": s, "before": sb or "voting", "after": sx or "voting"}
                )
    lost = [c for c in changes if c["before"] == "voting"]
    by = Counter((c["source"], c["before"], c["after"]) for c in changes)
    counts = {}
    for s in OTHER_IDP:
        counts[s] = {
            "votingBefore": sum(
                1 for r in rows_base.values() if r.get("assetClass") == "idp" and s in voting(r)
            ),
            "votingAfter": sum(
                1 for r in rows_x.values() if r.get("assetClass") == "idp" and s in voting(r)
            ),
        }
    return {
        "comparison": label,
        "statusChanges": changes,
        "statusChangeCounts": {f"{a}: {b} -> {c}": n for (a, b, c), n in sorted(by.items())},
        "votesLost": lost,
        "votingCounts": counts,
    }


def bucket_order(b: Any) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(b), -1)


def check_confidence(rows_d: dict, rows_c: dict) -> dict:
    """R6: confidence reflects DLF's added evidence (C vs D, IDP rows)."""
    trans = Counter()
    trans_vote = Counter()
    trans_novote = Counter()
    indep_delta = Counter()
    eligible_delta_novote = Counter()
    axis_changes = Counter()
    novote_changed = []
    for k, rc in rows_c.items():
        if rc.get("assetClass") != "idp":
            continue
        rd = rows_d.get(k)
        if not rd:
            continue
        dlf_votes = any(s in voting(rc) for s in DLF_IDP)
        t = (rd.get("confidenceBucket"), rc.get("confidenceBucket"))
        trans[t] += 1
        (trans_vote if dlf_votes else trans_novote)[t] += 1
        if dlf_votes:
            indep_delta[
                (rc.get("independentSourceCount") or 0) - (rd.get("independentSourceCount") or 0)
            ] += 1
        else:
            if rd.get("confidenceReasons") != rc.get("confidenceReasons"):
                novote_changed.append(
                    {
                        "row": k,
                        "before": rd.get("confidenceReasons"),
                        "after": rc.get("confidenceReasons"),
                    }
                )

            def _elig(rs):
                for x in rs or []:
                    m = re.search(r"of (\d+) eligible", str(x))
                    if m:
                        return int(m.group(1))
                return None

            eligible_delta_novote[
                str(
                    (_elig(rc.get("confidenceReasons")) or 0)
                    - (_elig(rd.get("confidenceReasons")) or 0)
                )
            ] += 1
        for ax, lv in (rc.get("confidenceAxes") or {}).items():
            lb = (rd.get("confidenceAxes") or {}).get(ax)
            if lb != lv:
                axis_changes[f"{ax}: {lb} -> {lv}"] += 1
    drivers = Counter()
    for k, rc in rows_c.items():
        rd = rows_d.get(k)
        if rc.get("assetClass") != "idp" or not rd or not any(s in voting(rc) for s in DLF_IDP):
            continue
        if bucket_order(rc.get("confidenceBucket")) < bucket_order(rd.get("confidenceBucket")):
            for ax, lv in (rc.get("confidenceAxes") or {}).items():
                if lv == rc.get("confidenceBucket") and bucket_order(lv) < bucket_order(
                    (rd.get("confidenceAxes") or {}).get(ax)
                ):
                    drivers[ax] += 1
    up = sum(n for (a, b), n in trans_vote.items() if bucket_order(b) > bucket_order(a))
    down = sum(n for (a, b), n in trans_vote.items() if bucket_order(b) < bucket_order(a))
    return {
        "bucketTransitionsAllIdp": {f"{a}->{b}": n for (a, b), n in sorted(trans.items(), key=str)},
        "bucketTransitionsDlfVotes": {
            f"{a}->{b}": n for (a, b), n in sorted(trans_vote.items(), key=str)
        },
        "bucketTransitionsDlfSilent": {
            f"{a}->{b}": n for (a, b), n in sorted(trans_novote.items(), key=str)
        },
        "independentFamilyDeltaWhereDlfVotes": {str(k): n for k, n in sorted(indep_delta.items())},
        "eligibleFamilyDeltaWhereDlfSilent": dict(eligible_delta_novote),
        "axisChanges": dict(sorted(axis_changes.items())),
        "dlfSilentRowsWhoseReasonsChanged": novote_changed[:40],
        "dlfSilentRowsWhoseReasonsChangedCount": len(novote_changed),
        "downgradeBottleneckAxesWhereDlfVotes": dict(drivers),
        "upgradesWhereDlfVotes": up,
        "downgradesWhereDlfVotes": down,
        "pass": set(indep_delta) <= {1}
        and not any(bucket_order(b) != bucket_order(a) for (a, b) in trans_novote),
    }


def check_board_consistency(c: dict, rows: dict[str, dict]) -> dict:
    """R7: IDP (and whole-board) consistency."""
    v = dc.validate_api_data_contract(c)
    ranked = sorted(
        (r for r in rows.values() if isinstance(r.get("canonicalConsensusRank"), int)),
        key=lambda r: r["canonicalConsensusRank"],
    )
    rank_inv = sum(1 for a, b in zip(ranked, ranked[1:]) if (val(a) or 0) < (val(b) or 0))
    ranks = [r["canonicalConsensusRank"] for r in ranked]
    contiguous = ranks == list(range(1, len(ranks) + 1))
    idp_ranked = [r for r in ranked if r.get("assetClass") == "idp"]
    idp_inv = sum(1 for a, b in zip(idp_ranked, idp_ranked[1:]) if (val(a) or 0) < (val(b) or 0))
    # DLF's own ordering survives translation: within each DLF IDP board, a
    # better DLF rank never receives a worse translated rank or a lower vote.
    order_breaks: dict[str, int] = {}
    for s_key in DLF_IDP:
        obs = sorted(
            (
                (m.get("rawRank"), m.get("effectiveRank"), m.get("valueContribution"))
                for r in rows.values()
                for m in [((r.get("sourceRankMeta") or {}).get(s_key))]
                if isinstance(m, dict) and isinstance(m.get("rawRank"), (int, float))
            ),
            key=lambda t: t[0],
        )
        order_breaks[s_key] = sum(
            1
            for a, b in zip(obs, obs[1:])
            if a[0] < b[0] and ((a[1] or 0) > (b[1] or 0) or (a[2] or 0) < (b[2] or 0))
        )
    out_of_scale = [
        k
        for k, r in rows.items()
        if r.get("rankDerivedValue") is not None
        and not (1 <= float(r.get("rankDerivedValue") or 0) <= 9999)
        and r.get("assetClass") != "pick"
    ]
    blend_viol = [
        k for k, r in rows.items() if "blend_integrity_violation" in (r.get("anomalyFlags") or [])
    ]
    idp_rows = [r for r in rows.values() if r.get("assetClass") == "idp"]
    return {
        "structuralErrors": v.get("structuralErrors"),
        "sourceHealthErrors": v.get("sourceHealthErrors"),
        "status": v.get("status"),
        "rankInversions": rank_inv,
        "ranksContiguous": contiguous,
        "rankedRows": len(ranks),
        "idpRankInversions": idp_inv,
        "idpRankedRows": len(idp_ranked),
        "dlfTranslationOrderBreaks": order_breaks,
        "idpPricedRows": sum(1 for r in idp_rows if val(r)),
        "idpQuarantined": sum(1 for r in idp_rows if r.get("quarantined")),
        "quarantined": sum(1 for r in rows.values() if r.get("quarantined")),
        "valuesOutsideScale": out_of_scale,
        "blendIntegrityViolations": blend_viol,
    }


def two_way(rows_by_board: dict[str, dict]) -> dict:
    out = {}
    for b, rows in rows_by_board.items():
        r = rows.get(TWO_WAY)
        if not r:
            continue
        out[b] = {
            "value": val(r),
            "rank": r.get("canonicalConsensusRank"),
            "altFamilyValue": (r.get("twoWayPlayerBoost") or {}).get("altFamilyValue"),
            "primaryFamilyValue": (r.get("twoWayPlayerBoost") or {}).get("primaryFamilyValue"),
            "altSourcesConsidered": (r.get("twoWayPlayerBoost") or {}).get("sourcesConsidered"),
            "altDropped": (r.get("twoWayPlayerBoost") or {}).get("droppedSources"),
            "dlfVotes": {
                s: (r.get("sourceRankMeta") or {}).get(s, {}).get("valueContribution")
                for s in DLF_ALL
                if s in voting(r)
            },
            "dlfIdpObservation": {
                k: (r.get("sourceRankMeta") or {}).get("dlfIdp", {}).get(k)
                for k in ("valueContribution", "method", "excludedReason")
            }
            if "dlfIdp" in (r.get("sourceRankMeta") or {})
            else None,
            "confidence": r.get("confidenceBucket"),
        }
    return out


def picks_and_trades(c_base: dict, c_x: dict, rows_base: dict, rows_x: dict) -> dict:
    """R9: derived picks move only through the rookie tether; trade engines read
    exactly the canonical value through one path."""
    moved = []
    prov = Counter()
    for k, r in rows_x.items():
        if r.get("assetClass") != "pick":
            continue
        b = rows_base.get(k)
        if b is None:
            continue
        if val(b) != val(r):
            p = r.get("pickValueProvenance")
            cls = p.get("class") if isinstance(p, dict) else p
            prov[str(cls)] += 1
            moved.append(
                {
                    "row": k,
                    "before": val(b),
                    "after": val(r),
                    "provenance": cls,
                    "basis": (p or {}).get("basis") if isinstance(p, dict) else None,
                }
            )
    bv_base = trade_finder.board_values_from_contract(c_base)
    bv_x = trade_finder.board_values_from_contract(c_x)
    canon_mismatch = 0
    for rows, bv in ((rows_base, bv_base), (rows_x, bv_x)):
        for r in rows.values():
            n = r.get("displayName")
            if val(r) and bv.get(n) is not None and bv[n] != val(r):
                # only possible where two rows share a display name (setdefault keeps the first)
                canon_mismatch += 1
    changed_assets = {n for n in set(bv_base) | set(bv_x) if bv_base.get(n) != bv_x.get(n)}
    changed_rows = {
        str(r.get(k))
        for rows_a, rows_b in ((rows_base, rows_x),)
        for key, r in rows_b.items()
        if val(rows_a.get(key)) != val(r)
        for k in ("legacyRef", "canonicalName", "displayName")
        if r.get(k)
    }
    trades = []
    for label, a, b in TRADE_SAMPLES:
        res = {"trade": label, "sideA": a, "sideB": b}
        for tag, bv in (("base", bv_base), ("target", bv_x)):
            av = [bv.get(n) for n in a]
            bvv = [bv.get(n) for n in b]
            if any(x is None for x in av + bvv):
                res[tag] = {"missing": [n for n, x in zip(a + b, av + bvv) if x is None]}
                continue
            res[tag] = {
                "sideA": av,
                "sideB": bvv,
                "rawGap": sum(av) - sum(bvv),
                "adjustedGap": trade_suggestions._va_gap(av, bvv),
            }
        trades.append(res)
    return {
        "movedPicks": moved,
        "movedPickProvenance": dict(prov),
        "tradeValueEqualsCanonicalMismatches": canon_mismatch,
        "tradeAssetsChanged": len(changed_assets),
        "tradeAssetsChangedNotExplainedByRowChange": sorted(changed_assets - changed_rows)[:20],
        "sampleTrades": trades,
    }


# ── impact ─────────────────────────────────────────────────────────────


def vote_diff(rb: dict | None, rx: dict | None) -> list[str]:
    """Source-level attribution for one row: votes added, removed, re-statused."""
    out = []
    mb = (rb or {}).get("sourceRankMeta") or {}
    mx = (rx or {}).get("sourceRankMeta") or {}
    for s in sorted(set(mb) | set(mx)):
        sb = status(rb, s) if s in mb else "absent"
        sx = status(rx, s) if s in mx else "absent"
        vb = (mb.get(s) or {}).get("valueContribution")
        vx = (mx.get(s) or {}).get("valueContribution")
        if sb != sx:
            out.append(f"{s} {vx if vx is not None else vb}: {sb or 'voting'} -> {sx or 'voting'}")
        elif sb is None and vb != vx and vb and vx:
            out.append(f"{s} vote {vb} -> {vx}")
    # the two-way alt-family panel (not in sourceRankMeta)
    tb = (rb or {}).get("twoWayPlayerBoost") or {}
    tx = (rx or {}).get("twoWayPlayerBoost") or {}
    if tb or tx:
        sb_, sx_ = set(tb.get("sourcesConsidered") or []), set(tx.get("sourcesConsidered") or [])
        for s in sorted(sx_ - sb_):
            out.append(f"two-way {tx.get('altFamily')} alt panel: {s} absent -> voting")
        for s in sorted(sb_ - sx_):
            out.append(f"two-way {tb.get('altFamily')} alt panel: {s} voting -> absent")
        if tb.get("altFamilyValue") != tx.get("altFamilyValue"):
            out.append(f"alt value {tb.get('altFamilyValue')} -> {tx.get('altFamilyValue')}")
    # picks: the evidence the value came from
    pb = (rb or {}).get("pickValueProvenance")
    px = (rx or {}).get("pickValueProvenance")
    if isinstance(px, dict) and val(rb) != val(rx):
        basis = px.get("basis")
        out.append(f"{px.get('class')}{f' ({basis})' if basis else ''}")
        if isinstance(pb, dict) and pb.get("class") != px.get("class"):
            out.append(f"pick provenance {pb.get('class')} -> {px.get('class')}")
    return out


def impact(rows_base: dict, rows_x: dict) -> tuple[list[dict], dict]:
    recs = []
    for k in sorted(set(rows_base) | set(rows_x)):
        rb, rx = rows_base.get(k), rows_x.get(k)
        vb, vx = val(rb), val(rx)
        kb = (rb or {}).get("canonicalConsensusRank")
        kx = (rx or {}).get("canonicalConsensusRank")
        cb = (rb or {}).get("confidenceBucket")
        cx = (rx or {}).get("confidenceBucket")
        if vb == vx and kb == kx and cb == cx:
            continue
        r = rx or rb or {}
        pct = (vx / vb - 1.0) * 100 if vb and vx else None
        recs.append(
            {
                "row": k,
                "assetClass": r.get("assetClass"),
                "position": r.get("position"),
                "rookie": bool(r.get("rookie")),
                "valueBefore": vb,
                "valueAfter": vx,
                "delta": (vx - vb) if vb is not None and vx is not None else None,
                "pct": round(pct, 2) if pct is not None else None,
                "rankBefore": kb,
                "rankAfter": kx,
                "idpRankBefore": (rb or {}).get("idpRank"),
                "idpRankAfter": (rx or {}).get("idpRank"),
                "confidenceBefore": cb,
                "confidenceAfter": cx,
                "pickProvenance": (
                    (r.get("pickValueProvenance") or {}).get("class")
                    if isinstance(r.get("pickValueProvenance"), dict)
                    else None
                ),
                "attribution": "; ".join(vote_diff(rb, rx)),
            }
        )
    summ: dict[str, Any] = {}
    for cls in ("offense", "idp", "pick"):
        sub = [
            x for x in recs if x["assetClass"] == cls and x["pct"] is not None and x["delta"] != 0
        ]
        n_cls = sum(1 for r in rows_x.values() if r.get("assetClass") == cls and val(r))
        absp = sorted(abs(x["pct"]) for x in sub)
        summ[cls] = {
            "pricedRows": n_cls,
            "valueMoved": len(sub),
            "up": sum(1 for x in sub if x["delta"] > 0),
            "down": sum(1 for x in sub if x["delta"] < 0),
            "medianAbsPctOfMoved": round(statistics.median(absp), 2) if absp else 0.0,
            "p90AbsPctOfMoved": round(absp[int(0.9 * (len(absp) - 1))], 2) if absp else 0.0,
            "maxAbsPct": round(absp[-1], 2) if absp else 0.0,
            "ge5pct": sum(1 for p in absp if p >= 5),
            "ge10pct": sum(1 for p in absp if p >= 10),
            "rankChangesGe25": sum(
                1
                for x in recs
                if x["assetClass"] == cls
                and isinstance(x["rankBefore"], int)
                and isinstance(x["rankAfter"], int)
                and abs(x["rankAfter"] - x["rankBefore"]) >= 25
            ),
            "enteredRankedBoard": sum(
                1
                for x in recs
                if x["assetClass"] == cls
                and x["rankBefore"] is None
                and isinstance(x["rankAfter"], int)
            ),
            "leftRankedBoard": sum(
                1
                for x in recs
                if x["assetClass"] == cls
                and isinstance(x["rankBefore"], int)
                and x["rankAfter"] is None
            ),
            "confidenceChanges": dict(
                Counter(
                    f"{x['confidenceBefore']}->{x['confidenceAfter']}"
                    for x in recs
                    if x["assetClass"] == cls and x["confidenceBefore"] != x["confidenceAfter"]
                )
            ),
        }

    def top_n(rows, n):
        return {
            str(r.get("displayName"))
            for r in rows.values()
            if isinstance(r.get("canonicalConsensusRank"), int) and r["canonicalConsensusRank"] <= n
        }

    for n in (100, 200):
        b, x = top_n(rows_base, n), top_n(rows_x, n)
        summ[f"top{n}"] = {"entered": sorted(x - b), "left": sorted(b - x)}
    return recs, summ


# ── rendering ──────────────────────────────────────────────────────────


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def verdict(ok: Any) -> str:
    return "PASS" if ok is True else ("FAIL" if ok is False else str(ok))


def render_readiness(tag: str, res: dict) -> str:
    L: list[str] = []
    a = L.append
    a(f"# DLF restoration readiness: {tag}")
    a("")
    a(
        "Directive §9 / prereg §15. Generated by `scripts/oiv2_dlf_readiness.py`; numbers are exact "
        "for this frozen input. V2 at provisional Stage 1 thresholds under NO-HISTORY: an R "
        "constraint check (deviation T1), never evidence, to be re-run on the frozen thresholds."
    )
    a("")
    a(
        f"* payload sha256 `{res['payloadSha256']}`; CSV + data tree listing hash `{res.get('inputsSha','?')}`"
    )
    a(
        f"* code `{res['codeSha']}`; build time and peak RSS are in the JSON (the only fields that differ on a rerun)"
    )
    a("")
    a("## Verdicts")
    a("")
    a(
        md_table(
            ["check", "question", "verdict"], [[c, q, verdict(v)] for c, q, v in res["verdicts"]]
        )
    )
    a("")
    r1 = res["R1"]
    a("## R1. One DLF family, one cap (board C'' and C)")
    a("")
    a(
        f"* correlation group of every DLF board: `{sorted(set(r1['C']['correlationGroups'].values()))}`; "
        f"provider: `{sorted(set(r1['C']['providers'].values()))}`"
    )
    for b in ("C", "C''"):
        x = res["R1"][b]
        a(
            f"* board {b}: {x['rowsWithTwoOrMoreDlfMembers']} rows carry two or more voting DLF boards "
            f"({x['memberCombinations']}); family-total > cap on {len(x['capViolations'])} rows; "
            f"`independentSourceCount` ≠ distinct voting families on {x['independentCountMismatchCount']} rows"
        )
    a("")
    ex = res["R1"]["C"]["examples"][:4]
    if ex:
        a(
            "Examples (board C): each member keeps its vote, the family's applied weight sums to one provider's authority."
        )
        a("")
        a(
            md_table(
                ["row", "member", "vote", "pre-cap weight", "familyAdjustment", "applied weight"],
                [
                    [
                        e["row"],
                        s,
                        m["value"],
                        m["preFamilyWeight"],
                        m["familyAdjustment"],
                        m["appliedWeight"],
                    ]
                    for e in ex
                    for s, m in e["members"].items()
                ],
            )
        )
        a("")
    r2 = res["R2"]
    a("## R2. Populations (board C)")
    a("")
    rows2 = []
    for s in DLF_IDP:
        x = r2[s]
        rows2.append(
            [
                s,
                x["csvEntries"],
                x["observationsOnBoard"],
                x["votingRows"],
                x["byAssetClass"],
                x["byPosition"],
                x["byRookie"],
                x["votesOnHeldBoardA"],
                len(x["csvEntriesWithoutObservation"]),
                len(x["positionVsDlfRawExport"]),
            ]
        )
    a(
        md_table(
            [
                "source",
                "CSV entries",
                "observations",
                "voting rows",
                "class",
                "position",
                "rookie?",
                "votes on held board A",
                "CSV entries with no row",
                "position ≠ DLF raw export",
            ],
            rows2,
        )
    )
    a("")
    for s in DLF_IDP:
        x = r2[s]
        if x["csvEntriesWithoutObservation"]:
            a(
                f"* {s} CSV entries with no observation on any row: {', '.join(map(str, x['csvEntriesWithoutObservation']))}"
            )
        if x["layerARefusals"]:
            a(f"* {s} Layer A refusals: {x['layerARefusals']}")
        a(f"* {s} on held board A: statuses {x['heldBoardAStatuses']}")
    a(
        f"* rows on which BOTH DLF IDP boards vote (shared cap, R1): {len(r2['rowsWithBothDlfIdpBoards'])} — "
        f"{', '.join(r2['rowsWithBothDlfIdpBoards'])}"
    )
    rn = r2["registryNote"]
    a(
        f"* registry declares `dlfIdp.excludes_rookies = {rn['dlfIdp.excludes_rookies']}`, but DLF's IDP board "
        f"now lists rookies: it votes on {rn['dlfIdpVotesOnRookieRows']} rookie rows (finding G1)."
    )
    a("")
    r3 = res["R3"]
    a("## R3. DLF Rookie IDP rookie-value translation")
    a("")
    a(
        f"* ladder reference `idpTradeCalc`, depth {r3['ladderDepth']}; every vote's method is "
        f"`rookie_ladder_translation_via_idpTradeCalc`: {verdict(not r3['wrongMethod'])}; effective rank equals "
        f"the ladder recomputed from the built board on {len(r3['entries']) - len(r3['effectiveRankMismatches'])} / "
        f"{len(r3['entries'])}; DLF's within-class order preserved: {verdict(r3['orderPreserved'])}"
    )
    a("")
    a(
        md_table(
            [
                "row",
                "DLF class rank",
                "translated rank",
                "ladder",
                "DLF vote",
                "IDPTC's own vote",
                "status",
            ],
            [
                [
                    e["row"],
                    e["rawRank"],
                    e["effectiveRank"],
                    e["ladderExpected"],
                    e["vote"],
                    e["idptcOwnVote"],
                    e["status"] or "voting",
                ]
                for e in r3["entries"]
            ],
        )
    )
    a("")
    a(
        "Fail-closed stress (`idpTradeCalc` disabled through the source-override path; the rookie ladder has no reference):"
    )
    a("")
    for lab, key in (
        ("V2 (C_noIDPTC)", "stressV2_noIDPTC"),
        ("incumbent (B_noIDPTC)", "stressIncumbent_noIDPTC"),
    ):
        x = r3[key]
        a(
            f"* {lab}: dlfRookieIdp {x['dlfRookieIdp']}; dlfIdp {x['dlfIdp']}; dlfIdp sharedMarketTranslated {x['dlfIdpSharedMarketTranslated']}, effective rank / board C {x['dlfIdpEffectiveRankRatioVsC']}"
        )
        for e in x["dlfRookieIdpTop3"]:
            a(
                f"  * class #{e['rawRank']} {e['row']}: effective rank {e['effectiveRank']}, vote {e['vote']}, "
                f"status {e['status'] or 'voting'}, row value {e['rowValue']}"
            )
    a("")
    r4 = res["R4"]
    a("## R4. DLF's own IDP votes are not rejected (boards C and C'')")
    a("")
    for b in ("C", "C''"):
        for s in DLF_IDP:
            x = r4[b][s]
            a(
                f"* {b} {s}: {x['reasonsV2']}; excluded {len(x['excludedV2'])}; kept as legitimate dissent "
                f"{len(x['keptDissentV2'])}"
            )
    for s in DLF_IDP:
        for d in r4["C"][s]["incumbentDropsBoardB"]:
            a(f"* contrast, incumbent on board B drops {s} on {d['row']} (vote {d['vote']})")
    kd = [e for s in DLF_IDP for e in r4["C"][s]["keptDissentV2"]]
    if kd:
        a("")
        a(
            md_table(
                ["row (C)", "DLF vote", "row value", "nearest other provider (u)"],
                [
                    [
                        e["row"],
                        e["vote"],
                        e["rowValue"],
                        (e["layerC"] or {}).get("nearestOtherProvider"),
                    ]
                    for e in kd
                ],
            )
        )
    a("")
    x = res["R10"]
    a("## R10. D4 (DLF Values, board C'')")
    a("")
    a(
        f"* voting rows {x['votingRows']} ({x['byAssetClass']}, {x['byPosition']}); votes on A {x['votesOnBoardA']}, on C {x['votesOnBoardC']}; "
        f"DLF Values picks votes {x['dlfValuesPicksVotes']}"
    )
    a(f"* statuses {x['reasons']}")
    for e in x["notVoting"]:
        a(f"  * not voting: {e['row']} (vote {e['vote']}): {e['status']}")
    for e in x["layerARefusals"]:
        a(f"  * Layer A refusal before ranking: {e['row']}: {e['verdict']} / {e['reason']}")
    a("")
    a("## R5. Draft Sharks / FantasyPros / IDP Trade Calculator keep voting when valid")
    a("")
    for key in ("C_vs_D", "C_vs_A", "Cpp_vs_Cp", "B_vs_A"):
        x = res["R5"][key]
        a(
            f"* **{x['comparison']}**: {len(x['statusChanges'])} non-DLF IDP status changes; votes lost {len(x['votesLost'])}"
        )
        for k2, n in x["statusChangeCounts"].items():
            a(f"  * {k2}: {n}")
        a(
            "  * voting rows before → after: "
            + "; ".join(
                f"{s} {v['votingBefore']} → {v['votingAfter']}"
                for s, v in x["votingCounts"].items()
            )
        )
    a("")
    r6 = res["R6"]
    a(
        "## R6. Confidence reflects the added evidence (C vs D, IDP rows; owner `src/api/confidence.py` unchanged)"
    )
    a("")
    a(
        f"* independent-family count change on rows where DLF votes: {r6['independentFamilyDeltaWhereDlfVotes']} (DLF counted once, R1)"
    )
    a(
        f"* bucket transitions where DLF votes: {r6['bucketTransitionsDlfVotes']} (up {r6['upgradesWhereDlfVotes']}, down {r6['downgradesWhereDlfVotes']})"
    )
    a(
        f"* axes that fell to the new (lower) bucket on those downgrades: {r6['downgradeBottleneckAxesWhereDlfVotes']}"
    )
    a(f"* bucket transitions where DLF is silent: {r6['bucketTransitionsDlfSilent']}")
    a(
        f"* eligible-family count change where DLF is silent: {r6['eligibleFamilyDeltaWhereDlfSilent']}; rows whose reasons changed {r6['dlfSilentRowsWhoseReasonsChangedCount']}"
    )
    a(f"* axis transitions: {r6['axisChanges']}")
    a("")
    a("## R7. Board consistency")
    a("")
    hdr = [
        "board",
        "status",
        "structural errors",
        "rank inversions",
        "ranks contiguous",
        "IDP rank inversions",
        "DLF translation order breaks",
        "IDP ranked / priced",
        "quarantined (IDP)",
        "outside 1–9999",
        "blend-integrity violations",
    ]
    rr = []
    for b, x in res["R7"].items():
        rr.append(
            [
                b,
                x["status"],
                len(x["structuralErrors"] or []),
                x["rankInversions"],
                x["ranksContiguous"],
                x["idpRankInversions"],
                x["dlfTranslationOrderBreaks"],
                f"{x['idpRankedRows']} / {x['idpPricedRows']}",
                f"{x['quarantined']} ({x['idpQuarantined']})",
                len(x["valuesOutsideScale"]),
                len(x["blendIntegrityViolations"]),
            ]
        )
    a(md_table(hdr, rr))
    a("")
    srch = {b: tuple(x["sourceHealthErrors"] or []) for b, x in res["R7"].items()}
    a(
        f"* source-health errors identical on every board: {verdict(len(set(srch.values())) == 1)} ({len(next(iter(srch.values())))} errors, input-dependent)"
    )
    a("")
    a("## R8. Two-way player (Travis Hunter)")
    a("")
    a(
        md_table(
            [
                "board",
                "published value",
                "rank",
                "offense (primary) value",
                "DB alt value",
                "alt sources",
                "alt dropped",
                "DLF offense votes",
                "confidence",
            ],
            [
                [
                    b,
                    x["value"],
                    x["rank"],
                    x["primaryFamilyValue"],
                    x["altFamilyValue"],
                    x["altSourcesConsidered"],
                    x["altDropped"],
                    x["dlfVotes"],
                    x["confidence"],
                ]
                for b, x in res["R8"].items()
            ],
        )
    )
    a("")
    a(
        "DLF IDP lists Travis Hunter as a defender; his DLF IDP observation enters only the two-way DB alt panel (`_two_way_alt_center`), never his offense panel, and inside the alt panel it is the `dlf` family's one vote."
    )
    a("")
    r9 = res["R9"]
    a("## R9. Downstream picks and trades (S2: C vs A)")
    a("")
    a(f"* moved picks {len(r9['movedPicks'])}, by provenance {r9['movedPickProvenance']}")
    a(
        f"* trade-engine board (`finder.board_values_from_contract`, the value every engine reads) differs from the canonical row value on {r9['tradeValueEqualsCanonicalMismatches']} rows; "
        f"{r9['tradeAssetsChanged']} trade assets change, {len(r9['tradeAssetsChangedNotExplainedByRowChange'])} not explained by a canonical row change"
    )
    a("")
    tr = []
    for t in r9["sampleTrades"]:
        b0, b1 = t.get("base", {}), t.get("target", {})
        tr.append(
            [
                t["trade"],
                f"{t['sideA']} vs {t['sideB']}",
                b0.get("sideA"),
                b0.get("sideB"),
                b0.get("adjustedGap"),
                b1.get("sideA"),
                b1.get("sideB"),
                b1.get("adjustedGap"),
            ]
        )
    a(
        md_table(
            [
                "sample",
                "packages",
                "A side (A)",
                "B side (A)",
                "adjusted gap (A)",
                "A side (C)",
                "B side (C)",
                "adjusted gap (C)",
            ],
            tr,
        )
    )
    a("")
    a(
        "Adjusted gap = `suggestions._va_gap` (the active package Value Adjustment, geom_q078_v1); the only input that changes between boards is the canonical value."
    )
    a("")
    return "\n".join(L) + "\n"


def render_impact(tag: str, imp: dict) -> str:
    L: list[str] = []
    a = L.append
    a(f"# Expected activation impact: {tag}")
    a("")
    a(
        "Exact for this frozen input (identical payload, CSVs, data, weights, configuration; only the "
        "DLF flags and the per-row filter differ). V2 at provisional thresholds, NO-HISTORY. Every row whose "
        f"value or confidence changes is listed in `impact_values_{tag}.csv` (every change, rank-only cascades included, in `impact_all_{tag}.csv.gz`) with its source-level attribution."
    )
    a("")
    hdr = [
        "scenario",
        "class",
        "priced rows",
        "value moved (up/down)",
        "median |Δ| of moved",
        "p90",
        "max",
        "≥5 %",
        "≥10 %",
        "rank Δ≥25",
        "confidence changes",
    ]
    rows = []
    for sid, label, b, x in SCENARIOS:
        s = imp[sid]["summary"]
        for cls in ("offense", "idp", "pick"):
            c = s[cls]
            rows.append(
                [
                    f"{sid} ({x} vs {b})" if cls == "offense" else "",
                    cls,
                    c["pricedRows"],
                    f"{c['valueMoved']} ({c['up']}/{c['down']})",
                    f"{c['medianAbsPctOfMoved']} %",
                    f"{c['p90AbsPctOfMoved']} %",
                    f"{c['maxAbsPct']} %",
                    c["ge5pct"],
                    c["ge10pct"],
                    c["rankChangesGe25"],
                    c["confidenceChanges"] or "",
                ]
            )
    a(md_table(hdr, rows))
    a("")
    for sid, label, b, x in SCENARIOS:
        s = imp[sid]["summary"]
        a(f"## {sid}: {label} — board {x} vs {b}")
        a("")
        for n in (100, 200):
            t = s[f"top{n}"]
            a(f"* top-{n} membership: entered {t['entered'] or 'none'}; left {t['left'] or 'none'}")
        recs = [r for r in imp[sid]["rows"] if r["pct"] is not None and r["delta"]]
        big = sorted(recs, key=lambda r: -abs(r["pct"]))[:15]
        if big:
            a("")
            a(
                md_table(
                    [
                        "row",
                        "class",
                        "pos",
                        "before",
                        "after",
                        "Δ %",
                        "rank",
                        "confidence",
                        "attribution",
                    ],
                    [
                        [
                            r["row"],
                            r["assetClass"],
                            r["position"],
                            r["valueBefore"],
                            r["valueAfter"],
                            r["pct"],
                            f"{r['rankBefore']} → {r['rankAfter']}",
                            f"{r['confidenceBefore']} → {r['confidenceAfter']}",
                            r["attribution"][:220],
                        ]
                        for r in big
                    ],
                )
            )
        a("")
    return "\n".join(L) + "\n"


# ── main ───────────────────────────────────────────────────────────────


def main() -> int:
    payload, tag, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    raw_bytes = payload.read_bytes()
    raw = json.loads(raw_bytes)
    secs: dict[str, float] = {}
    rows_by: dict[str, dict] = {}
    keep_full: dict[str, dict] = {}
    res: dict[str, Any] = {
        "schema": "oiv2-dlf-readiness/v1",
        "pin": tag,
        "payloadSha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    for b in BOARDS:
        t = time.time()
        c = build(b, raw)
        secs[b] = round(time.time() - t, 2)
        rows_by[b] = compact(c)
        if b in ("A", "C", "C''", "D", "C'"):
            keep_full[b] = c
        log(f"{tag} {b}: {len(rows_by[b])} rows, {secs[b]}s")
    res["buildSeconds"] = secs
    res["R1"] = {b: check_family_cap(rows_by[b]) for b in ("C", "C''")}
    res["R2"] = check_populations(rows_by["C"], rows_by["A"])
    res["R3"] = check_rookie_translation(rows_by["C"], rows_by["C_noIDPTC"], rows_by["B_noIDPTC"])
    res["R4"] = {b: check_dlf_not_rejected(rows_by[b], rows_by["B"]) for b in ("C", "C''")}
    res["R10"] = check_d4(rows_by["C''"], rows_by["C"], rows_by["A"])
    res["R5"] = {
        "C_vs_D": check_others_keep_voting(
            rows_by["D"], rows_by["C"], "C vs D (DLF IDP added under V2)"
        ),
        "C_vs_A": check_others_keep_voting(
            rows_by["A"], rows_by["C"], "C vs A (production → V2 + DLF IDP)"
        ),
        "Cpp_vs_Cp": check_others_keep_voting(
            rows_by["C'"], rows_by["C''"], "C'' vs C' (DLF IDP added under V2 + D4)"
        ),
        "B_vs_A": check_others_keep_voting(
            rows_by["A"], rows_by["B"], "B vs A (contrast: DLF IDP added under the incumbent)"
        ),
    }
    res["R6"] = check_confidence(rows_by["D"], rows_by["C"])
    res["R7"] = {
        b: check_board_consistency(keep_full[b], rows_by[b]) for b in ("A", "D", "C", "C'", "C''")
    }
    res["R8"] = two_way({b: rows_by[b] for b in ("A", "B", "D", "C", "C'", "C''")})
    res["R9"] = picks_and_trades(keep_full["A"], keep_full["C"], rows_by["A"], rows_by["C"])
    imp = {}
    for sid, label, b, x in SCENARIOS:
        recs, summ = impact(rows_by[b], rows_by[x])
        imp[sid] = {"label": label, "base": b, "target": x, "summary": summ, "rows": recs}
    res["impact"] = imp
    r5ok = all(not res["R5"][k]["votesLost"] for k in ("C_vs_D", "Cpp_vs_Cp"))
    r5_ca_lost = res["R5"]["C_vs_A"]["votesLost"]
    r7ok = all(
        not x["structuralErrors"]
        and x["rankInversions"] == 0
        and x["ranksContiguous"]
        and x["idpRankInversions"] == 0
        and not any(x["dlfTranslationOrderBreaks"].values())
        and not x["valuesOutsideScale"]
        and not x["blendIntegrityViolations"]
        for x in res["R7"].values()
    )
    r8 = res["R8"]
    r8ok = (
        all(r8[b]["value"] is not None for b in r8)
        and all("dlfIdp" not in (r8[b]["altSourcesConsidered"] or []) for b in ("A", "D", "C'"))
        and all("dlfIdp" in (r8[b]["altSourcesConsidered"] or []) for b in ("C", "C''"))
        and all(not r8[b]["altDropped"] for b in ("D", "C", "C'", "C''"))
        and all(r8[b]["value"] == r8[b]["altFamilyValue"] for b in r8)
    )
    r9 = res["R9"]
    r9ok = (
        set(r9["movedPickProvenance"]) <= {"rookie_pool_tether"}
        and r9["tradeValueEqualsCanonicalMismatches"] == 0
        and not r9["tradeAssetsChangedNotExplainedByRowChange"]
    )
    res["verdicts"] = [
        (
            "R1",
            "DLF IDP / Rookie IDP vote inside the one DLF family cap; never a second DLF family vote",
            res["R1"]["C"]["pass"] and res["R1"]["C''"]["pass"],
        ),
        (
            "R2",
            "correct populations (IDP only, rookie board on rookies only, held on A)",
            res["R2"]["pass"],
        ),
        (
            "R3",
            "DLF Rookie IDP translated through its IDPTC ladder; fails closed without it (V2)",
            res["R3"]["pass"],
        ),
        (
            "R4",
            "DLF's own IDP votes not rejected under V2",
            res["R4"]["C"]["pass"] and res["R4"]["C''"]["pass"],
        ),
        ("R5", "DS / FP / IDPTC keep voting when DLF is added under V2 (C vs D, C'' vs C')", r5ok),
        (
            "R5b",
            f"C vs A: other-source IDP votes lost = {len(r5_ca_lost)} (V2 Layer A / B decisions, independent of DLF)",
            "INFO",
        ),
        (
            "R6",
            "confidence reflects the added evidence (DLF = +1 family where it votes; no bucket change where silent)",
            res["R6"]["pass"],
        ),
        (
            "R7",
            "board consistency (structural lane, ranks, IDP ranks, scale, blend integrity)",
            r7ok,
        ),
        (
            "R8",
            "two-way player: published value = DB alt value; dlfIdp in the alt panel only where restored; V2 drops nothing",
            r8ok,
        ),
        (
            "R9",
            "picks move only through the rookie tether; trade engines read the one canonical value",
            r9ok,
        ),
        (
            "R10",
            "D4: DLF Values votes offense only, held on A / C, never priced as picks, no Layer C drop of its own votes",
            res["R10"]["pass"],
        ),
    ]
    res["peakRssMb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    res["codeSha"] = (vr._git("rev-parse", "HEAD") or "?").strip()[:10]
    sha_file = out / f"inputs_{tag}.sha"
    res["inputsSha"] = sha_file.read_text().strip() if sha_file.is_file() else "?"
    (out / f"READINESS_{tag}.md").write_text(render_readiness(tag, res), encoding="utf-8")
    (out / f"IMPACT_{tag}.md").write_text(render_impact(tag, imp), encoding="utf-8")
    cols = [
        "scenario",
        "base",
        "target",
        "row",
        "assetClass",
        "position",
        "rookie",
        "valueBefore",
        "valueAfter",
        "delta",
        "pct",
        "rankBefore",
        "rankAfter",
        "idpRankBefore",
        "idpRankAfter",
        "confidenceBefore",
        "confidenceAfter",
        "pickProvenance",
        "attribution",
    ]

    def _write(fh, only_material: bool) -> None:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for sid, _label, b, x in SCENARIOS:
            for r in imp[sid]["rows"]:
                if (
                    only_material
                    and r["valueBefore"] == r["valueAfter"]
                    and r["confidenceBefore"] == r["confidenceAfter"]
                ):
                    continue
                w.writerow({"scenario": sid, "base": b, "target": x, **r})

    # value or confidence changes, plain; every change incl. rank-only cascades, gzipped
    with (out / f"impact_values_{tag}.csv").open("w", newline="", encoding="utf-8") as fh:
        _write(fh, True)
    buf = io.StringIO()
    _write(buf, False)
    with gzip.GzipFile(out / f"impact_all_{tag}.csv.gz", "wb", mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    slim = {k: v for k, v in res.items() if k != "impact"}
    slim["impactSummary"] = {
        sid: {
            "label": v["label"],
            "base": v["base"],
            "target": v["target"],
            "summary": v["summary"],
        }
        for sid, v in imp.items()
    }
    (out / f"readiness_{tag}.json").write_text(
        json.dumps(slim, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"pin": tag, "verdicts": res["verdicts"], "peakRssMb": res["peakRssMb"]}, default=str
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
