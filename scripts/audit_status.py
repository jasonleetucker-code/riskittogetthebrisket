#!/usr/bin/env python3
"""Track which decision-intelligence audit findings are actually still open.

WHY THIS EXISTS
---------------
The 2026-08-04 audit
(``docs/audits/decision-intelligence-audit-2026-08-04.md``) was written
against commit ``9c5d972``.  Work landed after it — #704, #706, #713,
#715, #717 — and some of it closed audit findings incidentally.  The
remediation brief lists five as done; the real number is larger, and
the cited ``file:line`` evidence has drifted (the trade finder's
position read moved from ``:477`` to ``:529``, its IDP warning from
``:992`` to ``:1061``).

Without this file, "41 Criticals closed" is an unfalsifiable claim of
exactly the kind the audit exists to stop — it happened *because*
plausible-looking numbers went unchecked for months.  So the count is
kept as data, each entry carries the evidence justifying its status,
and the probes re-run in CI.

WHAT A PROBE PROVES — AND WHAT IT DOES NOT
------------------------------------------
Each entry names a **defect signature**: a fragment of source that is
present exactly while the defect's mechanism is present.  A probe
reports only whether that fragment is still in the file.  That is a
tripwire, not a correctness proof:

  * signature ABSENT  → the cited mechanism changed.  It does not
    follow that the defect is fixed; it may have moved.
  * signature PRESENT → the mechanism is untouched.  It does not
    follow that the defect is live; surrounding semantics may differ.

``status`` is therefore set by someone who READ the code, and
``verifiedBy`` records what they read.  The probe's job is to fire when
a recorded status and the tree disagree — a finding marked ``closed``
whose signature reappears is a regression, and that deserves a red
build.

WHY THE SIGNATURES ARE HAND-WRITTEN
-----------------------------------
The first cut derived them automatically from the registry's evidence
prose.  It cannot work: the registry backticks *source* and *measured
output* identically — ``retail_mean = sum(retail_ranks) / len(...)`` is
code, ``Counter({'1-for-2': 441, '1-for-1': 8})`` is a reproduction
result that was never in any file.  An extractor that cannot tell them
apart reports live defects as absent, which silently disarms the
tripwire.  Each signature below was confirmed by reading the file it
names.

USAGE
-----
    python scripts/audit_status.py --rebuild   # refresh, keep human fields
    python scripts/audit_status.py             # re-run probes, report drift

Exit codes: 0 no drift, 1 drift detected, 2 error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "docs" / "audits" / "decision-intelligence-audit-2026-08-04.registry.json"
STATUS = REPO_ROOT / "docs" / "audits" / "decision-intelligence-audit-2026-08-04.status.json"

OPEN, CLOSED, DEFERRED, REVIEW = "open", "closed", "deferred", "needs_review"

# Registry findings carry no IDs; the audit prose does (T-1, V-3, …), and
# so do the remediation plan and every PR description.  Keying by
# registry ORDER is stable: the registry is a frozen committed artifact,
# never regenerated.
#
# Each entry: (auditId, path, signature, status, verifiedBy)
# A signature of None means no mechanical probe — the note says why.
_FINDINGS: dict[str, tuple[str, str | None, str | None, str, str]] = {
    "C01": (
        "D-1",
        "frontend/lib/draft-logic.js",
        "Math.min(theoreticalMaxBid, winByCompetitor)",
        OPEN,
        "Read the clamp: it caps against the richest RIVAL only. Neither "
        "myRemaining nor mySlotsRemaining appears in either figure.",
    ),
    "C02": (
        "D-2",
        "frontend/lib/draft-logic.js",
        "const inflationDegraded = !(expectedPoolRemaining > 0)",
        REVIEW,
        "The Math.max(1, …) the audit cited is GONE — replaced by an "
        "explicit degraded-state guard. But remainingLeague / "
        "expectedPoolRemaining still grows without bound as the "
        "denominator approaches 0 from above, so the hyperbolic "
        "divergence needs re-measuring before this is called closed.",
    ),
    "C03": (
        "D-3",
        "src/api/draft_capital_fallback.py",
        None,
        CLOSED,
        "The hardcoded {1: 7000, 2: 4000, …} table is gone. "
        "_pick_value_from_contract returns None on a miss and callers "
        "stamp isUnpriced; the docstring records the removal. "
        "Closed before this pass, by the work CLAUDE.md documents as D-2.",
    ),
    "C04": (
        "V-3",
        "frontend/lib/dynasty-data.js",
        "full: Math.round(backendValue || rawValues.full)",
        OPEN,
        "Live at two materializer sites, plus four coercions of the same "
        "shape in frontend/app/rankings/page.jsx "
        "(row.rankDerivedValue || row.values?.full || 0), including the "
        "sort comparators at :596-597.",
    ),
    "C05": (
        "T-1",
        "frontend/lib/trade-logic.js",
        "result[i].given += value",
        OPEN,
        "The GIVE convention is live at :1393 while the verdict names the "
        "bigger pile the winner. Both conventions still present.",
    ),
    "C06": (
        "W-1",
        "server.py",
        None,
        CLOSED,
        "FAAB pool denominator no longer counts draft picks (#715). "
        "Recorded twice in the registry — see C42, the same defect.",
    ),
    "C07": (
        "W-2",
        "src/trade/waiver.py",
        None,
        CLOSED,
        "Closed by #707 while this batch was open — caught by this "
        "registry's own drift probe, not by noticing. The pool-relative "
        "`0.05 + 0.25 * (value / best on the wire)` is gone; "
        "_compute_faab_bid is now a shim over src/trade/faab_engine, "
        "whose ceiling is pinned to league-format anchors, and "
        "top_value_in_pool is accepted and ignored. Measured on the "
        "surface capture: a player at value 2000 now bids $20 on a rich "
        "wire AND $20 on a picked-over one, where before it was $11 vs "
        "$28 — the wire-dependence the finding was about is gone.",
    ),
    "C08": (
        "S-2",
        "src/api/data_contract.py",
        "retail_mean = sum(retail_ranks) / len(retail_ranks)",
        OPEN,
        "Raw ordinals averaged across pools of different depth, and the "
        "sole retail anchor is a TE-premium board while the consensus is "
        "not. Same mechanism as S-1 (C19).",
    ),
    "C09": (
        "S-3",
        "frontend/app/edge/page.jsx",
        "(r.sourceRankSpread ?? 0) > PREMIUM_SUMMARY_SPREAD",
        OPEN,
        "Panels still gate and sort on sourceRankSpread while taking sign "
        "from marketGapDirection — magnitude and sign come from different "
        "quantities.",
    ),
    "C10": (
        "S-4",
        "frontend/lib/display-helpers.js",
        "if (diff < MARKET_GAP_MIN_DIFF)",
        OPEN,
        "A second, different threshold for the same backend field as the " "/edge panels use.",
    ),
    "C11": (
        "S-6",
        "src/api/data_contract.py",
        "write_snapshot=not source_overrides",
        OPEN,
        "The shared rank snapshot is still written on any build without "
        "source overrides, and rankChange still diffs a board whose "
        "source set may have changed.",
    ),
    "C12": (
        "V-4",
        "frontend/components/useSettings.js",
        "tepMultiplier: 1.15",
        OPEN,
        "Default is still a finite number, so every session posts an "
        "explicit operator override and the ADR-015 curve never runs.",
    ),
    "C13": (
        "O-4",
        ".github/workflows/verify-sharp-production.yml",
        None,
        CLOSED,
        "Fixed in batch C2. All FOUR workflows force-add now — the audit "
        "named the pattern and a sweep found the other three "
        "(force-sharp-production-now, trigger-sharp-no-environment, "
        "trigger-sharp-now-via-merge). Verified with git check-ignore: no "
        "unguarded `git add data/` remains. The commit step also stops "
        "failing on an unchanged artifact, so the enforce gate below it "
        "can execute for the first time.",
    ),
    "C14": (
        "O-4b",
        ".github/workflows/verify-sharp-production.yml",
        None,
        CLOSED,
        "Fixed in batch C2, though NOT by adding auth — there is no "
        "credential to add. /api/sharp/* sits behind _private_api_gate and "
        "the workflow declares no secrets at all, so it structurally "
        "cannot authenticate. A 401 is now terminal rather than retryable: "
        "it means the service is up and correctly refusing an anonymous "
        "caller, which is a definitive answer, not a blip. The loop breaks "
        "with status unverifiable_unauthenticated instead of spending 80 "
        "attempts x 30s = 40 MINUTES on every push to main. The enforce "
        "gate reports that as insufficient evidence — loud, not fatal — "
        "and names the bearer pattern that would make it enforcing.",
    ),
    "C15": (
        "O-3",
        "server.py",
        None,
        CLOSED,
        "Fixed in batch C2. Confirmed on the pinned export first: "
        "result['sites'] carries exactly 2 entries against a 21-source "
        "registry, so the ratio test blocked only on total loss. The guard "
        "now also requires every anchor the payload declares in "
        "coverageAudit.expectedSites — no invented threshold, no hardcoded "
        "source name. The ratio test is KEPT alongside it because a "
        "malformed payload yields 'no anchors known missing', which is not "
        "'all present'. Pinned by tests/api/test_scrape_promotion_guard.py "
        "including the exact 1-of-2 case the old guard published.",
    ),
    "C16": (
        "O-1",
        "src/api/ops_alerts.py",
        None,
        CLOSED,
        "Fixed in batch C2. Was worse than the audit recorded: the key was attached at "
        "server.py:4352 inside the /api/status route only; "
        "_scrape_status_payload — what check_and_alert is actually "
        "called with — never sets it. And _scrape_success_rate_24h() "
        "returns a DICT, so float(rate) would raise even if it arrived. "
        "Two independent reasons the alert cannot fire.",
    ),
    "C17": (
        "V-1",
        "src/api/data_contract.py",
        'if src_def.get("is_cross_market"):',
        OPEN,
        "_curve_for_source tests is_cross_market FIRST, so IDP-scoped "
        "sources route to GLOBAL and the IDP master curve is applied to "
        "nothing it was fit on. Fit/apply overlap is zero.",
    ),
    "C18": (
        "V-1b",
        "src/api/data_contract.py",
        "_hampel_filter_per_player",
        OPEN,
        "Runs over the mixed-scale value list produced by C17; measured "
        "at 28% ejection of the designated IDP anchor.",
    ),
    "C19": (
        "S-1",
        "src/api/data_contract.py",
        "retail_mean = sum(retail_ranks) / len(retail_ranks)",
        OPEN,
        "Same site and mechanism as C08 — the registry records the pool "
        "normalization and the TE-basis consequence as separate findings.",
    ),
    "C20": (
        "V-2",
        "src/model_registry/holdout.py",
        '"FantasyCalc": ("CSVs/site_raw/fantasyCalc.csv", "value")',
        OPEN,
        "All four holdout boards are still registered live blend sources.",
    ),
    "C21": (
        "V-2b",
        "src/model_registry/holdout.py",
        None,
        OPEN,
        "The gate rewards the value-decay property those four boards were "
        "moved off the value-direct path for. No single line encodes it — "
        "it is a property of the scoring objective; closed together with "
        "C20.",
    ),
    "C22": (
        "T-4",
        "src/trade/finder.py",
        None,
        CLOSED,
        "Positions are plumbed via positions_from_contract; the read at "
        ":529 is (positions or {}).get(name) or pdata.get('position'). "
        "The comment narrates the exact defect in past tense.",
    ),
    "C23": (
        "T-5",
        "src/trade/finder.py",
        None,
        CLOSED,
        "league_has_idp at :1061 reads the plumbed positions map, so the "
        "IDP-blindness warning can fire. Closed with C22.",
    ),
    "C24": (
        "T-6",
        "src/trade/finder_value_adjustment.py",
        "market_value=value + adjustment",
        OPEN,
        "The package Value Adjustment is still applied to the market side "
        "only, manufacturing arbitrage from a scale asymmetry.",
    ),
    "C25": (
        "T-7",
        "src/trade/finder.py",
        "if len(give) > len(receive):",
        OPEN,
        "Multi-piece guards still gate on the give-more direction only; "
        "the 1-for-N direction is unguarded.",
    ),
    "C26": (
        "T-9",
        "src/trade/suggestions.py",
        "analyze_roster(roster_names, pool, starter_needs)",
        OPEN,
        "Still called with a name list the pool can only partly resolve.",
    ),
    "C27": (
        "T-10",
        "src/trade/monte_carlo.py",
        "p90=_shifted(cv * 1.15)",
        OPEN,
        "The invented ±15% band is still the fallback, and no producer " "populates valueBand.",
    ),
    "C28": (
        "B-1",
        None,
        None,
        DEFERRED,
        "Not verifiable from the repository: data/ is gitignored, so the "
        "absence of data/bdvm/ in a clone proves nothing about "
        "production. Requires deployment access to confirm whether the "
        "timer has run since the 2026-07-30 deploy.sh fix.",
    ),
    "C29": (
        "B-2",
        "src/nfl_data/realized_points.py",
        '"rec": ("receptions", "Rec")',
        OPEN,
        "_SIMPLE_KEYS carries flat 'rec' and no rec_0_4 / rec_5_9 / "
        "rec_10_19 band keys, so the active reception-band rules score "
        "nothing.",
    ),
    "C30": (
        "P-1",
        "src/sharp/score.py",
        'float(weights.get("rosterQuality", 0.22)) * roster',
        OPEN,
        "Weighted at 0.22 and structurally zero, with no renormalization "
        "of the remaining weights.",
    ),
    "C31": (
        "P-2",
        "scripts/crawl_sharp_activity.py",
        "def qualified_sleeper_ids()",
        OPEN,
        "Activity evidence is still collected only for already-qualified " "managers.",
    ),
    "C32": (
        "P-3",
        "src/intel/crawler.py",
        "if not owner or owner not in pool:",
        OPEN,
        "Both sides of a cohort-internal trade are dropped, so the trade "
        "adds volume and confidence but no direction.",
    ),
    "C33": (
        "R-3",
        "frontend/lib/team-phase.js",
        "if (isHighValue && isYounger) return PHASES.WIN_NOW;",
        OPEN,
        "The frontend 2x2 median-split classifier is still live alongside "
        "roster_intel/window.py and ros/direction.py.",
    ),
    "C34": (
        "R-3b",
        "src/ros/trade_deadline.py",
        "owner_ids = sorted(set(playoffs) | set(champs) | set(strengths))",
        OPEN,
        "CONFIRMED against live data — data/ros/ is the tracked exception "
        "to the data/ gitignore, so this one IS checkable from the repo. "
        "data/ros/sims/latest_playoff.json carries 8 rows for a 12-team "
        "league, and its playoffOdds are exactly [1.0 x6, 0.0 x2] with "
        "converged: true on 2000 sims. That single file is the evidence "
        "for three findings at once: the 8-of-12 scale mix here, the "
        "degenerate 100%/0% odds (C35), and the four absent owners that "
        "the union at this line admits and the ladder then labels Seller "
        "(C36, C38). Probed on the union because that is the line the "
        "fix changes.",
    ),
    "C35": (
        "N-1",
        "src/ros/playoff_sim.py",
        "schedule = _remaining_schedule(snapshot)",
        OPEN,
        "An empty remaining schedule still yields degenerate 100%/0% odds "
        "stamped converged: true.",
    ),
    "C36": (
        "N-2",
        "src/ros/trade_deadline.py",
        'float((playoffs.get(owner) or {}).get("playoffOdds") or 0.0)',
        OPEN,
        "A missing owner is still coerced to 0.0 and labelled Seller.",
    ),
    "C37": (
        "L-1",
        "src/league_intel/replacement.py",
        "def _safe_drop(",
        OPEN,
        "structuralScarcity still derives from a log-rank index with an "
        "arbitrary zero, so factors move with source universe size.",
    ),
    "C38": (
        "N-2b",
        "src/ros/trade_deadline.py",
        "owner_ids = sorted(set(playoffs) | set(champs) | set(strengths))",
        OPEN,
        "The union still admits owners present in only one input, which "
        "is how a missing team reaches the BUY/SELL ladder at all. Closed "
        "together with C36.",
    ),
    "C39": (
        "E-1",
        "src/api/injury_impact.py",
        "BASE_DISCOUNT_PCT",
        OPEN,
        "A keyword-matched headline still discounts a user-facing value "
        "by up to 5%, and 'info' severity means no keyword matched at all.",
    ),
    "C40": (
        "E-2",
        "src/news/providers/_rss.py",
        'return "watch", kind, "positive"',
        OPEN,
        "Every WATCH item is still stamped positive, including 'released' " "and 'waived'.",
    ),
    "C41": (
        "X-5",
        "src/api/draft_capital_fallback.py",
        None,
        CLOSED,
        "Same defect as C03 — the invented per-round table is gone and "
        "unpriced picks are marked rather than fabricated.",
    ),
    "C42": (
        "W-1b",
        "server.py",
        None,
        CLOSED,
        "Same defect as C06 (#715) — the registry records the bid desk "
        "and the waiver module as separate findings.",
    ),
    "C43": (
        "Z-2",
        None,
        None,
        CLOSED,
        "Fixed in batch C2, at the STAMPING layer rather than the preserve "
        "layer — preserving last-good is correct and desirable; claiming "
        "it was fetched is not. stamp_if_present already required the CSV "
        "to be newer than a pre-scraper marker, and that guard was "
        "DEFEATED because the scraper's restore pass rewrites the "
        "preserved board with open(dest,'wb') during the run, giving it a "
        "current mtime and a full row count. The scraper already records "
        "the answer — manifest.json carries siteRawPreserved — and nothing "
        "consulted it. stamp_if_present now skips any board listed there. "
        "Exercised in a real shell across four paths (preserved / fresh / "
        "corrupt manifest / missing manifest); the last two fall back to "
        "the mtime gate so one bad manifest cannot suppress stamping "
        "everywhere.",
    ),
}

_PATH_RE = re.compile(
    r"\b((?:src|frontend|scripts|tests|config|deploy|docs|\.github)/[\w./\-]+\.\w+"
    r"|server\.py|Dynasty Scraper\.py)(?::(\d+))?"
)


def _squash(text: str) -> str:
    """Strip whitespace so formatting alone cannot mask a live defect.

    Signatures are quoted from source, but ``ruff format`` and Prettier
    are both free to reflow a statement across lines without changing
    behaviour.  Comparing with whitespace removed matches modulo
    formatting; a changed identifier, operator or literal still fails,
    which is what the probe is for.
    """
    return re.sub(r"\s+", "", text)


def _probe(path: str | None, needle: str | None) -> dict[str, Any]:
    """Report whether a defect signature is still present at ``path``."""
    if not path or not needle:
        return {"result": "no_mechanical_probe"}
    target = REPO_ROOT / path
    if not target.exists():
        return {"result": "file_missing", "path": path, "needle": needle}
    try:
        body = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # noqa: BLE001 — a probe reports, it never crashes the sweep
        return {"result": "unreadable", "path": path, "needle": needle, "error": str(exc)}
    return {
        "result": "signature_present" if _squash(needle) in _squash(body) else "signature_absent",
        "path": path,
        "needle": needle,
    }


def _registry_criticals() -> list[dict[str, Any]]:
    areas = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    n = 0
    for area in areas:
        label = str(area.get("area") or area.get("subsystem") or "?")
        for f in area.get("findings", []):
            if str(f.get("severity", "")).lower() != "critical":
                continue
            n += 1
            out.append(
                {
                    "id": f"C{n:02d}",
                    "title": f.get("title"),
                    "area": label,
                    "complexity": f.get("complexity"),
                    "auditEvidence": str(f.get("evidence") or "")[:400],
                }
            )
    return out


def rebuild() -> int:
    """Refresh derived fields, preserving remediation bookkeeping."""
    prior: dict[str, dict[str, Any]] = {}
    if STATUS.exists():
        prior = {
            e["id"]: e for e in json.loads(STATUS.read_text(encoding="utf-8")).get("findings", [])
        }

    entries = []
    for e in _registry_criticals():
        curated = _FINDINGS.get(e["id"])
        if curated is None:
            raise SystemExit(
                f"{e['id']} has no curated signature entry — add one before rebuilding"
            )
        audit_id, path, needle, status, verified = curated
        old = prior.get(e["id"], {})
        e.update(
            {
                "auditId": audit_id,
                "path": path,
                "signature": needle,
                # STATUS HAS ONE AUTHORITY: the curated table above, which
                # lives in code and moves through review with the batch that
                # closes the finding.  It is deliberately NOT merged with the
                # prior JSON — letting the generated file win would give this
                # field two sources that drift apart, which is the defect
                # class the whole audit is about.
                "status": status,
                "verifiedBy": verified,
                "closedBy": old.get("closedBy"),
                "measuredEffect": old.get("measuredEffect"),
                "batch": old.get("batch"),
                "probe": _probe(path, needle),
            }
        )
        entries.append(e)

    tally: dict[str, int] = {}
    for e in entries:
        tally[e["status"]] = tally.get(e["status"], 0) + 1

    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(
        json.dumps(
            {
                "source": REGISTRY.name,
                "severity": "Critical",
                "total": len(entries),
                "tally": tally,
                "findings": entries,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"rebuilt {len(entries)} Critical entries -> {STATUS.relative_to(REPO_ROOT)}")
    for k in sorted(tally):
        print(f"  {k:>12}: {tally[k]}")
    return 0


def check() -> int:
    if not STATUS.exists():
        print(f"error: {STATUS} missing — run --rebuild first", file=sys.stderr)
        return 2
    findings = json.loads(STATUS.read_text(encoding="utf-8")).get("findings", [])

    drift = []
    tally: dict[str, int] = {}
    for e in findings:
        tally[e.get("status", "?")] = tally.get(e.get("status", "?"), 0) + 1
        recorded = e.get("probe") or {}
        if recorded.get("result") in (None, "no_mechanical_probe"):
            continue
        now = _probe(recorded.get("path"), recorded.get("needle"))
        if e.get("status") == CLOSED and now["result"] == "signature_present":
            drift.append((e, "defect signature returned"))
        elif e.get("status") == OPEN and now["result"] != recorded["result"]:
            drift.append((e, f"probe changed: {recorded['result']} -> {now['result']}"))

    print(f"Critical findings: {len(findings)}")
    for k in sorted(tally):
        print(f"  {k:>12}: {tally[k]}")
    if drift:
        print(f"\nDRIFT ({len(drift)}):")
        for e, why in drift:
            print(f"  {e['id']} ({e.get('auditId')}) {str(e['title'])[:52]} — {why}")
        return 1
    print("\nno drift: every recorded status matches its probe.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="refresh probes and derived fields")
    args = ap.parse_args()
    try:
        return rebuild() if args.rebuild else check()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — report, never traceback at the operator
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
