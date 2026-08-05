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
        REVIEW,
        "PARTLY CLOSED, and the headline half is gone — re-measured in "
        "batch C3 by running buildRows over the real contract. The audit "
        "reported 260 rows promoting the raw scraper composite into the "
        "Value column, 158 of them above the deepest genuinely-priced "
        "player. Measured now: 261 rows the board declines to price, and "
        "ZERO render a non-zero number. The math audit's H1 fix made "
        "inferValueBundle return the board value only, so both sides of "
        "the `backendValue || rawValues.full` expression now derive from "
        "rankDerivedValue and the composite can no longer reach the "
        "column. The expression survives and looks like the defect, "
        "which is why this stays flagged rather than closed.\n\n"
        "WHAT REMAINS is the same defect class one step milder: those "
        "261 rows render 0, which asserts 'worth nothing' rather than "
        "'not priced', and 0 sorts and aggregates as a real value. That "
        "is the Unknown render rule (em-dash, sorts last, excluded from "
        "aggregates with the exclusion counted) and it is frontend-wide "
        "work — the type landed in C3 with the two ROS sites; this is "
        "scoped to its own batch rather than half-done here.",
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
        None,
        CLOSED,
        "Fixed in batch C4 — but NOT by the mechanism the audit proposed, "
        "and the measurement is the reason. The brief said the tight ends "
        "read SELL because the sole retail anchor is a TE-premium board "
        "and the consensus is not, implying that normalizing or splitting "
        "the bases would fix it. Measured on the live board, neither "
        "does: 68 of 72 TEs read retail_premium, percentile "
        "normalization moved that to 66, restricting the consensus side "
        "to TEP-native peers moved it to 63. Reading the rows explains "
        "why — KTC ranks AJ Barner 121 and EVERY other source ranks him "
        "139-248. The TE reading was arithmetically CORRECT all along; "
        "it is the TE++ basis the whole board is anchored on (ADR-015) "
        "showing through, and no normalization can remove a true fact.\n\n"
        "The actual defect is that a definitional constant was being "
        "presented as a tradeable signal. Median gap in rank space by "
        "position: TE +121, PICK -109, against WR +20 / RB +16 / QB -7 "
        "per-mille — a 6x separation. Subtracting each position's median "
        "leaves the per-player disagreement, which survives rather than "
        "being annihilated (within TEs the de-meaned gap still spans "
        "Jack Endries -281 to Elijah Arroyo +145). Measured effect: TE "
        "68/72 -> 36/72 retail_premium, PICK 35/36 -> 18/36, every "
        "position balanced. marketGapAbsoluteMagnitude keeps the "
        "pre-de-meaning number, because that is what a trade with a "
        "KTC-anchored partner actually turns on. The basis is stamped at "
        "methodology.marketGap so the correction is falsifiable.",
    ),
    "C09": (
        "S-3",
        "frontend/app/edge/page.jsx",
        None,
        CLOSED,
        "Fixed in batch C4, and it was worse than recorded. The premium "
        "panels did not merely take magnitude and sign from different "
        "quantities — they FILTERED and SORTED on sourceRankSpread, how "
        "much the sources disagree with each other, while displaying "
        "marketGapDirection's sign. So a clean large gap on a player "
        "every source agreed about was EXCLUDED, and a negligible gap on "
        "a player the sources were arguing over sorted FIRST: the panel "
        "structurally surfaced its least reliable rows and hid its most "
        "reliable. The gate also barely gated — measured, it admitted "
        "376 of the 414 rows carrying a gap (91%). marketGapMagnitude, "
        "the magnitude OF the direction being filtered on, was stamped "
        "by the backend all along and read by nothing here.\n\n"
        "Two more instances found beyond the recorded one: "
        "edge-helpers.py's topRetailPremium/topConsensusPremium did the "
        "same thing AND rendered it, printing 'Sell +45 ranks' where 45 "
        "was the disagreement width described to the user as the gap. "
        "All four now gate, sort and label on marketGapMagnitude. "
        "PREMIUM_SUMMARY_SPREAD is retained but narrowed to the "
        "disagreements panel and the disagreement stat, which are "
        "genuinely about sources disagreeing.",
    ),
    "C10": (
        "S-4",
        "frontend/lib/display-helpers.js",
        None,
        CLOSED,
        "Fixed in batch C4. The recorded finding was 'a second, different "
        "threshold', which undersold it: display-helpers.js was not just "
        "thresholding the backend field differently, it was RECOMPUTING "
        "the whole retail-vs-consensus comparison client-side from raw "
        "ordinals (marketEdge, marketAction, marketGapLabel all rebuilt "
        "the two means locally). That is a second authority for a number "
        "the contract already stamps — the same shape as the "
        "computeUnifiedRanks fallback removed from buildRows, and it "
        "carried S-1 independently.\n\n"
        "All three now read the stamps verbatim. The reason they had "
        "grown a local copy is itself fixed: the contract used to "
        "collapse 'only retail ranked him', 'only the experts did' and "
        "'nobody did' into one bare \"none\", so the helper recomputed to "
        "recover the distinction — the backend now stamps "
        "marketGapUnknown.reason (C3's vocabulary). Four thresholds "
        "gating one concept are now one entry each in "
        "config/thresholds.json, with the JSON as the source, Python "
        "LOADING it so it cannot drift, and "
        "tests/api/test_threshold_parity.py enforcing the JS mirror — "
        "replacing a hand-written 'mirror these Python constants' "
        "comment. idpMarketEdge is deliberately LEFT on the ordinal "
        "path and documented as such: the backend emits no IDP gap at "
        "all, so deleting it would remove a working surface to satisfy "
        "a rule. Tracked as the IDP-anchor follow-up.",
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
        None,
        CLOSED,
        "Fixed in batch C4 by src/api/rank_space.py: every cross-source "
        "rank comparison now happens in RANK SPACE (a rank divided by "
        "the observed depth of its own board) instead of on raw "
        "ordinals. Confirmed and quantified on the live board first — "
        "the registered sources publish between 278 and 900 rows, a 3.2x "
        "spread, and normalizing flips the sign of the gap on 42% of "
        "offense rows and 35 of 36 picks (the audit said 47%/97%; the "
        "pick figure matches exactly). The concrete case: draftSharks "
        "rank 143 of 683 is a BETTER placement than ktcSfTep rank 121 of "
        "469, and ordinal arithmetic said the reverse.\n\n"
        "Depths are OBSERVED per build rather than read from the "
        "registry's declared depth field, which is None for most sources "
        "and describes intent rather than what arrived. Board effect "
        "measured through the harness: 0 values, 0 ranks, 0 tiers moved; "
        "177 marketGapDirection flips. A market_gap surface was added to "
        "golden_surfaces.py BEFORE the claim, per the plan's trap 7.",
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
        None,
        CLOSED,
        "Closed on main by #734 while batch C4 was open — NOT by this "
        "pass, and picked up here rather than reverted. Batch C12 no "
        "longer needs to fix P-1.\n\n"
        "_roster_quality_component now returns None (not 0.0) when it "
        "has no evidence, and the scoring sum renormalizes over the "
        "components that do; the unconditional "
        '`float(weights.get("rosterQuality", 0.22)) * roster` term is '
        "gone and components.weightsApplied is stamped per manager so "
        "the renormalization is auditable rather than assumed.\n\n"
        "Found by diffing main's generated status.json against this "
        "table during the C4 merge — the file is generated, so resolving "
        "the conflict by regenerating would have silently reverted the "
        "closure. Worth knowing for every future merge: the generated "
        "artifact is not the authority, but it IS the only place another "
        "PR's closure shows up.",
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
        None,
        CLOSED,
        "Fixed in batch C3. With no remaining schedule the simulation "
        "loop drew no games, so all 2000 'simulations' replayed the "
        "standings and every team landed on exactly 1.0 or 0.0 — stamped "
        "converged: true, in August, before a 2026 game was played. The "
        "fix does NOT refuse every empty schedule, because a FINISHED "
        "season is the same shape and there 1.0/0.0 is a fact: it "
        "separates the two on whether any games have been played, and "
        "returns an empty board with an explicit unsimulable reason only "
        "when nothing has been played AND nothing is scheduled. "
        "simulate_playoff_odds therefore emits no odds rather than "
        "certain ones, which is what lets C36's classifier report "
        "'Insufficient evidence' instead of reading a 0.0.",
    ),
    "C36": (
        "N-2",
        "src/ros/trade_deadline.py",
        None,
        CLOSED,
        "Fixed in batch C3, and MEASURED on the live cache rather than "
        "asserted: build_team_directions over data/ros/ moved FOUR "
        "managers (Brent, Kich, Blaine, jstuedle) from 'Seller' to "
        "'Insufficient evidence' — Brent being rank #1 in the league on "
        "ROS strength, told to sell his roster for no reason but absence "
        "from an 8-row sim file in a 12-team league. The two genuinely "
        "measured 0% teams (Ed, Collin) still read Seller, which is the "
        "control: the fix withholds fabricated answers without silencing "
        "real ones. Absent owners are still LISTED (dropping them would "
        "trade one wrong answer for another) with null odds, a "
        "machine-readable reason, measurable: false, and a label that "
        "reuses none of the seven buy/sell verbs. They sort last rather "
        "than as the worst team. Pinned by "
        "tests/ros/test_trade_deadline_unknown.py, including a live-data "
        "case that fails if any unmeasurable row ever regains a sell "
        "verb.",
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
        None,
        CLOSED,
        "Closed with C36, but note the union at this line was deliberately "
        "KEPT. Narrowing it to the intersection would have hidden four "
        "real managers to avoid mislabelling them — a league that appears "
        "to have 8 teams is its own wrong answer. What changed is what "
        "the union's extra rows are allowed to say: they reach the "
        "classifier no longer, and carry an explicit refusal instead of a "
        "coerced 0.0.",
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
