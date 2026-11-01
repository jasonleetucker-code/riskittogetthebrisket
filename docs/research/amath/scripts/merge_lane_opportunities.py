"""Merge the five AMATH lane opportunity files into one ranked, deduplicated matrix.

ARTIFACT GENERATOR (the one deliberate exception to "diagnostics write nothing"): it
regenerates docs/research/amath/evidence/sitewide_opportunities_merged.json from the five
lane files, deterministically, and writes nothing else.

Run from the repository root:  python -I <this file> <repo-root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
EV = ROOT / "docs" / "research" / "amath" / "evidence"
LANES = ["valuation", "trades", "projections", "roster", "frontier"]
KEYS = [
    "id",
    "category",
    "domain",
    "title",
    "current_system",
    "code_owner",
    "status",
    "current_method",
    "evidence",
    "evidence_class",
    "baseline",
    "proposed",
    "principle",
    "mechanism",
    "data_available",
    "data_missing",
    "consumers",
    "risk",
    "evaluation",
    "acceptance",
    "rejection",
    "effort",
    "horizon",
    "related_roadmap",
    "novelty_note",
    "scores",
]
SCORE_KEYS = [
    "advantage",
    "justification",
    "data",
    "feasibility",
    "strategic",
    "interpretability",
    "efficiency",
]

rows: dict[str, dict] = {}
for lane in LANES:
    for r in json.loads((EV / f"{lane}_opportunities.json").read_text(encoding="utf-8")):
        assert list(r.keys()) == KEYS, r["id"]
        rows[r["id"]] = r


def rr(x) -> str:
    return "; ".join(x) if isinstance(x, list) else str(x)


def uniq_join(vals, sep="; "):
    out, seen = [], set()
    for v in vals:
        for part in [p.strip() for p in str(v).split(";")]:
            if part and part.lower() not in seen:
                seen.add(part.lower())
                out.append(part)
    return sep.join(out)


def tagged(ids, key):
    return " | ".join(f"[{i}] {rr(rows[i][key])}" for i in ids)


def sc(**kw):
    d = {k: kw[k] for k in SCORE_KEYS}
    d["total"] = sum(d.values())
    return d


# ---------------------------------------------------------------- group spec
# Each group: lane ids (first = primary), plus overrides.  Unlisted fields are copied
# (single source) or tagged-concatenated (multi source).
G: list[dict] = []


def g(ids, **ov):
    G.append({"ids": ids, **ov})


# ---- multi-lane merges -------------------------------------------------------
g(
    ["AM-PROJECTIONS-04", "AM-PROJECTIONS-05", "AM-FRONTIER-02", "AM-ROSTER-02", "AM-VALUATION-03"],
    category="N",
    title="Forecast Calibration Ledger: schedule AL-3b/AL-4a, size-controlled gates, calibration-state on every published probability/interval, and outcome reliability of confidence buckets",
    proposed=(
        "One calibration ledger (reuses src/model_registry/projection_scorecard.py and game_day_calibration.py, "
        "src/ros/forecast_archive.py, trade/decision logs) run weekly on finalized data: reliability, Brier/log score, "
        "CRPS, PIT and 50/80/90 coverage by position x provider x state; component-first ladder (weekly matchup "
        "probability, team-week CRPS) before season-level gates; every gate's pass rate for a perfectly calibrated "
        "synthetic model computed at the real sample size and admitted only if >= 90%; one calibrationState descriptor "
        "(unverified / failing / tracking n, Brier, slope) read by every probability surface; and a reliability study of "
        "HIGH/MEDIUM/LOW confidence buckets against later value revision, controlling for depth and season phase"
    ),
    mechanism=(
        "Measures before modelling: makes every other probabilistic item adjudicable and stops overclaiming while "
        "dispersion is fallback. Gate sizing fixes the documented defect that a perfect model passes SC-G4 0.2% and "
        "SC-G1 16% of the time at week-7 sizes"
    ),
    evaluation=(
        "Existence and weekly freshness of the ledger; per-gate operating characteristics at actual n; confidence-bucket "
        "LR test over a depth-only model (VALUATION POC-V2); no frozen preregistration is re-scored"
    ),
    acceptance=(
        "Ledger runs weekly with no temporal-guard violations; every probability surface carries the descriptor; every "
        "admitted gate passes a calibrated synthetic model >= 90%; confidence buckets either show HIGH<MED<LOW revision in "
        ">= 80% of folds with significant information over depth, or the gate is simplified to depth + family count"
    ),
    rejection=(
        "Ledger cannot be produced without post-kickoff data; or gates cannot be size-controlled at available n (then report "
        "descriptively, never gate on them)"
    ),
    effort="1-2 days scheduling + 2-4 days ledger/badge plumbing + 2-3 days gate OC work; confidence reliability study 3-5 days",
    horizon="P0",
    scores=sc(
        advantage=18,
        justification=19,
        data=12,
        feasibility=14,
        strategic=10,
        interpretability=10,
        efficiency=5,
    ),
    rescore="Primary AM-PROJECTIONS-04 (87). Strategic 9->10: five lanes independently found that their probability/interval "
    "items are unadjudicable without this ledger and correctly sized gates, so its consumer set is sitewide.",
    extra_roadmap="#2053 S3 / AMATH-3 (calibration method, extended not duplicated); AL-3b; AL-4a; RPA-LGI-004; RPA-F-029; MD-11; MD-4; D11; SIM_CALIBRATION V3 gate sizing; B11",
)

g(["AM-VALUATION-01"], scores=None)  # single-source, copied

g(
    ["AM-ROSTER-01", "AM-FRONTIER-01", "AM-PROJECTIONS-03"],
    category="E",
    title="Shared latent factors in simulation draws: season-level team-strength uncertainty (playoff/title) and game/team correlation (Game Day, BBLI, playoff)",
    proposed=(
        "(a) Playoff/title engine: draw a team-mean offset u_t ~ N(0, tau_t^2) once per simulated season from a "
        "normal-normal posterior (prior presim/league mean, likelihood scored weeks), optional local-level drift. "
        "(b) Weekly draws: one shared N(0, tau^2) factor per NFL game side plus a smaller same-team factor "
        "(V3-D4 method), then if needed a Gaussian copula over quantile marginals reusing the paused DFS correlation-prior "
        "architecture re-implemented in a live owner (DFS not resumed). Loadings fit only on earlier seasons/weeks, "
        "empirical-Bayes shrunk toward 0"
    ),
    mechanism=(
        "Season-total variance becomes n*sigma^2 + n^2*tau^2 instead of n*sigma^2, de-saturating odds; stacks and "
        "opponents on one roster change team-total variance in a roster-dependent direction that independence ignores"
    ),
    evaluation=(
        "ROSTER POC-1 (weekly matchup log score, seed RPS, size-controlled gates) for (a); FRONTIER POC-1 (CRPS of "
        "team-week totals, A1 vs A0, week-clustered bootstrap) for (b); (b) runs only after the weekly marginals item"
    ),
    acceptance=(
        "(a) matchup log-score gain 95% CI > 0, seed RPS not worse, holds under the D11-corrected arm; (b) team-total "
        "CRPS CI excludes 0 in favour of the factor arm, no secondary worse beyond margin, signs consistent with football logic"
    ),
    rejection=(
        "Gains vanish under the D11-corrected arm; tau unstable across folds (CV > 50%); calibration improves only by "
        "uniform widening; fitted correlation signs contradict football logic in > 2 preregistered pairs"
    ),
    effort="3-5 engineer-days research for (a); 5-8 for (b) after marginals",
    horizon="P1",
    scores=sc(
        advantage=21,
        justification=17,
        data=12,
        feasibility=13,
        strategic=9,
        interpretability=8,
        efficiency=5,
    ),
    rescore="Primary AM-ROSTER-01 (85) kept; no rescore. Novelty correction: the D11 record in docs/OWNER_REQUESTED_TODO.md already "
    "names a 'per-draw team shock' as the pre-sim calibration work its failed gate G4 points at, so component (a) is a "
    "codebase confirmation of a recorded follow-up, not an unrecorded discovery.",
    extra_roadmap="#2053 S6 (joint dependence) and pure-math row 6 (joint season calibration); D11 G4 follow-up; MD-11; FFBB-5",
)

g(
    ["AM-PROJECTIONS-01", "AM-PROJECTIONS-02", "AM-PROJECTIONS-14", "AM-FRONTIER-09"],
    category="R",
    title="Measured weekly predictive marginals: replace fallback CVs, SD-proportional-to-remaining in-progress scaling and the truncated Gaussian with PIT-measured, position-pooled (empirical-Bayes) dispersion, sqrt(f) remainder scaling and a hurdle/skewed shape",
    proposed=(
        "Position CVs (optionally EB-shrunk per player, heteroskedastic in the mean) measured from week-8+ pregame-archive "
        "residuals, refit weekly from PIT data only; in-progress remainder SD proportional to f^gamma with gamma = 0.5 fixed "
        "for the primary test; hurdle P(near 0) x lognormal/gamma positive part as a shape challenger"
    ),
    mechanism=(
        "Every displayed Game Day probability currently uses FALLBACK_CV_BY_POSITION (QB 0.32 ... TE 0.65) because the "
        "calibrated artifact was never built (RPA-F-021); late-game SD shrinks proportional to f instead of sqrt(f) "
        "(0.50x at f = 0.25)"
    ),
    evaluation="PROJECTIONS PoC-1: player-week CRPS and PIT coverage, weeks 10-14 preregistered before 2026-11-12, player-cluster bootstrap, Bonferroni over 3 challengers",
    acceptance=(
        "Delta-CRPS 98.33% CI lower > 0 pooled, no position significantly worse, pooled 80% PIT coverage in [0.75, 0.85] "
        "and no position outside [0.70, 0.90]; gamma = 0.5 only if AL-4a late-bucket reliability is not worse"
    ),
    rejection="Delta-CRPS CI upper < 0; coverage reached only with intervals >= 1.5x wider and no CRPS gain; realized/predicted mean drifts outside [0.85, 1.15]",
    effort="2-4 days after enough archived weeks",
    horizon="P0",
    scores=sc(
        advantage=20,
        justification=19,
        data=11,
        feasibility=14,
        strategic=8,
        interpretability=8,
        efficiency=4,
    ),
    rescore="Primary AM-PROJECTIONS-01 (84) kept; the merged rows (68, 61, 64) are components of the same PoC and do not raise it.",
    extra_roadmap="#2053 S3 / AMATH-3; RPA-F-021; AL-4a; GAME_DAY_PROBABILITY_SPEC section 6",
)

g(
    ["AM-VALUATION-02", "AM-FRONTIER-07"],
    category="N",
    title="Dynasty value uncertainty band: family-bootstrap band now (named alternate concept) and a stratified, outcome-calibrated revision-risk interval later",
    proposed=(
        "familyBootstrapBand: resample voting families and re-run the count-aware blend (display-only, never "
        "rankDerivedValue); then a revision-risk interval from stratified empirical/adaptive-conformal quantiles of "
        "|delta log value| over horizon h by depth x asset class x season phase, labelled uncalibrated until per-stratum coverage passes"
    ),
    mechanism="Gives the 'is 3,286 really different from 3,350' answer and a real per-asset band to replace the synthetic +/-15% band the trade Monte Carlo consumes",
    evaluation="VALUATION POC-V2 (rolling quantiles, ~6 non-overlapping folds, Wilson coverage per stratum)",
    acceptance="80% coverage in [0.75, 0.85] in every major stratum across folds with width <= the depth-only baseline",
    rejection="Coverage error > 0.10 in any major stratum, or coverage only at widths covering most of the scale",
    effort="2-3 days bootstrap band; 4-6 days revision interval",
    horizon="P1",
    scores=dict(rows["AM-VALUATION-02"]["scores"]),
    rescore="Primary AM-VALUATION-02 (83) kept.",
    extra_roadmap="open-modeling-decisions #4; #2053 S3 (dynasty analogue, kept separate from weekly/ROS)",
)

g(
    ["AM-TRADES-01", "AM-TRADES-08"],
    category="N",
    title="Market Clearing Percentile plus board-noise decomposition of accepted-trade residuals",
    proposed=(
        "Conditional distribution of clearing residuals r = (U_A - U_B)/max(U_A, U_B) given shape, noise-balanced level and "
        "pick share, from PIT-priced completed market trades (rolling, league-disjoint calibration, EB pooling of sparse "
        "cells); plus log|r| = b0 + b_shape + gamma*log(sigma_board) + ... to measure how much 'unfairness' is board noise. "
        "Private, labelled market behaviour, never fairness"
    ),
    mechanism="Answers whether a deal of this shape and gap actually clears, which the normative bands cannot (6 of 29 reconstructed own-league trades read 'fair')",
    evaluation="TRADES PoC-1 (prospective >= 2,000 unequal-count trades after a preregistered freeze; league-cluster bootstrap)",
    acceptance="Prospective 80% coverage in [0.75, 0.85] pooled, every shape in [0.70, 0.90], interval score beats unconditional quantiles; gamma > 0 in both source families",
    rejection="Coverage out of band or no interval-score gain (keep descriptive aggregates only); gamma CI includes 0",
    effort="4-6 engineer-days on the box",
    horizon="P1",
    scores=dict(rows["AM-TRADES-01"]["scores"]),
    rescore="Primary AM-TRADES-01 (82) kept; AM-TRADES-08 (75) is hypothesis H2 of the same PoC.",
    extra_roadmap="#2053 pure-math row 8 (trade utility/market); OD-F4",
)

g(
    ["AM-FRONTIER-04", "AM-TRADES-03"],
    category="REMOVE",
    title="Hide or relabel the live trade Monte Carlo 'win rate' built on a synthetic flat +/-15% band; replace only once real per-asset bands exist",
    proposed=(
        "Owner decision: hide the win-rate (or relabel it as a deterministic transform of the gap) now; re-introduce a "
        "probability only from the dynasty value band item, never from synthetic bands"
    ),
    mechanism="0 of 1,093 rows carry a real valueBand, so the UI synthesises +/-15% and the output is a monotone function of the gap dressed as a probability (anti-pattern A4)",
    evaluation="Owner decision; then a contract test that no synthetic-band probability is displayed",
    acceptance="No synthetic-band probability displayed as information",
    rejection="n/a (removal); a replacement is rejected if its band fails the value-band item's coverage gate",
    effort="0.5-1 engineer-day after the decision (flag monte_carlo_trade exists)",
    horizon="P0",
    scores=dict(rows["AM-TRADES-03"]["scores"]),
    rescore="Primary AM-TRADES-03 (80) kept. Horizon P1 -> P0: two lanes independently found a live surface presenting a non-informative number as a probability; that is a correctness/honesty defect, not a modelling opportunity.",
    extra_roadmap="NC-D; MD-11; open-modeling-decisions #4; backlog spec 1.5 Monte Carlo audit; #2053 section 1 item 6",
)

g(
    ["AM-ROSTER-06", "AM-ROSTER-14"],
    category="N",
    title="Roster Fragility Index and Hidden Weakness (expected points at risk per slot) from one exact-lineup scenario engine",
    proposed=(
        "Weekly best-ball score distribution F_w(R) from BBLI draw-then-solve plus the bye calendar, P(plays) for uncertain "
        "players and one same-NFL-team shock; index = (E[F] - CVaR10[F]) / E[F]; EPaR_s = sum_w sum_p P(absent) x "
        "(score_p - backfill_p,w) as the per-slot decomposition"
    ),
    mechanism="Surfaces lower-tail lineup risk and slots that look fine on mean but rest on one fragile player; no second model",
    evaluation="Reliability of predicted fragile weeks against realized lineup shortfalls; ledger coverage of team-week lower quantiles",
    acceptance="Predicted lower-tail quantiles of team-week totals covered at nominal rate within ledger tolerance; EPaR ranks slots with realized shortfall better than the weakness thresholds",
    rejection="Lower-tail coverage fails, or the index only restates bye weeks",
    effort="4-6 days after the marginals and shared-factor items",
    horizon="P2",
    scores=dict(rows["AM-ROSTER-06"]["scores"]),
    rescore="Primary AM-ROSTER-06 (81) kept; ROSTER doc states AM-ROSTER-14 is a decomposition of the same engine.",
    extra_roadmap="FFBB-2; FFBB-5; MD-28/RCV-4; feature row 1.2",
)

g(
    ["AM-TRADES-05", "AM-TRADES-04", "AM-FRONTIER-12"],
    category="N",
    title="Regret and No-Action layer (private shadow): No-Action Advantage, regret/CVaR versus hold, and regret cards with NO ACTION always shown",
    proposed=(
        "NAA = P(U_hold >= U_trade) and E[(U_trade - U_hold)+] from existing paired BBLI draws plus a gap posterior; later "
        "a multi-season regret simulator U = sum_t delta^t P(title_t) w + lambda * terminal value with CVaR10 of the "
        "difference, robust across {GEOM, KTC, VG} package views; display as 'cost if wrong' cards"
    ),
    mechanism="Makes NO ACTION an explicit scored option and separates 'both outcomes fine' from 'small expected gain, large tail loss'",
    evaluation="Shadow decision agreement/disagreement explained; proper scoring of its probabilistic components via the ledger; no promotion without outcome labels",
    acceptance="Components pass ledger calibration; shadow regret replay shows lower decision regret than the deterministic champion on archived decisions",
    rejection="Inputs uncalibrated (title odds, value returns) or no regret improvement in replay",
    effort="3-5 days NAA; 8-12 days full regret simulator",
    horizon="P2",
    scores=dict(rows["AM-TRADES-05"]["scores"]),
    rescore="Primary AM-TRADES-05 (76) kept.",
    extra_roadmap="FFBB-4; C7-DESK-01; C7-BEST-TRADE; #2053 S4 (decision theory, simple scenario form first)",
)

g(
    ["AM-ROSTER-09", "AM-TRADES-16"],
    category="E",
    title="Pick-slot forecasts: fix simulator overconfidence upstream, score by RPS, then fit pick-market c with log score, reliability and cross-season pooling",
    proposed="Repair the sim (shared-latent-factor item) first, score slot forecasts by Ranked Probability Score by origin week, then fit c on residual miscalibration with a beta prior pooled across seasons once the 24-outcome bucket fills",
    mechanism="c currently compensates post hoc for upstream simulator overconfidence",
    acceptance="Slot RPS improves after the upstream fix; c fitted only on residual miscalibration with reliability diagrams",
    rejection="Fewer than 24 outcomes per bucket (stay provisional, cap 0.5)",
    effort="2-3 days after the sim item",
    horizon="P2",
    scores=dict(rows["AM-ROSTER-09"]["scores"]),
    rescore="Primary AM-ROSTER-09 (76) kept.",
    extra_roadmap="C1-U7; C7-PICKGEN-01",
)

g(
    ["AM-VALUATION-17", "AM-FRONTIER-10"],
    category="N",
    title="Exact leave-one-family-out evidence explainer and one Disagreement Map ('who is mispriced')",
    proposed="Recompute the blend without each family (k <= ~15 per row) and publish V - V_-f plus the censor bound; surface per-family vote strips with coverage ('8 of 11 eligible families') and the bottleneck axis named, on one page",
    mechanism="Replaces a weighted-mean explainer that the Valuation Advancement Map showed does not equal the blend; consolidates UX-P06's five 'who is mispriced' surfaces",
    acceptance="Explainer reproduces the published blend exactly; anomaly alarm fires on rows where one family moves the value by a large share",
    rejection="Recomputation cost breaks contract-build budget",
    effort="3-5 days",
    horizon="P1",
    scores=dict(rows["AM-VALUATION-17"]["scores"]),
    rescore="Primary AM-VALUATION-17 (76) kept.",
    extra_roadmap="UX-P06; MD-31",
)

g(
    ["AM-TRADES-10", "AM-TRADES-11"],
    category="R",
    title="Empirical-Bayes partial pooling for small-sample manager tendencies, archetypes and Sharp Score win%",
    proposed="Beta-binomial / Dirichlet-multinomial / gamma-Poisson pooling toward a declared (league-level) prior with 80% intervals; archetypes as P(rate > threshold) >= 0.8; Sharp all-play win% shrunk and league-strength adjusted with snowball-selection sensitivity",
    mechanism="A 2-of-3 '67% consolidator' is noise (SE about 0.29 at n = 3); hard cut-offs create cliffs",
    acceptance="Posterior intervals published, insufficient_sample kept when posterior ~ prior; rank stability across seasons improves versus raw shares",
    rejection="Prior choice dominates conclusions (sensitivity analysis shows label flips across reasonable priors)",
    effort="3-4 days",
    horizon="P1",
    scores=dict(rows["AM-TRADES-10"]["scores"]),
    rescore="Primary AM-TRADES-10 (77) kept.",
    extra_roadmap="C6-MGR-01; Sharp workstream; MD-32",
)

g(
    ["AM-VALUATION-05", "AM-VALUATION-04"],
    category="R",
    title="One predictive selection target for board constants chosen on stability (alpha = 0.10 shrinkage, freshness curve C4, Hampel floor), including re-selection of alpha",
    proposed="Reuse src/source_quality leave-family-out future agreement as the loss; stability becomes a guard, not the objective; alpha re-selected (scalar or empirical-Bayes per row) under that target",
    mechanism="alpha = 0.10 was selected jointly with lambda = 0.10 and lambda is now 0, so its selection basis no longer exists; stability losses are minimized by ignoring information",
    acceptance="Selected constants beat incumbents on the predictive target with block-bootstrap CI excluding 0 and no stability guard breach",
    rejection="No constant beats the incumbent (keep incumbents, record the evidence)",
    effort="4-6 days",
    horizon="P1",
    scores=dict(rows["AM-VALUATION-05"]["scores"]),
    rescore="Primary AM-VALUATION-05 (76) kept.",
    extra_roadmap="AL-1; AL-1b; AL-1c; C10 prior census",
)

g(
    ["AM-ROSTER-12", "AM-VALUATION-12"],
    category="E",
    title="BDVM hazards and aging curves: position-pooled discrete-time survival with dropout/selection correction",
    proposed="Hierarchical discrete-time hazard splines and position-pooled aging, rolling-origin by season, with players leaving the league treated as informative dropout",
    acceptance="Held-out log score / Brier of hazards improves versus params_v1 priors without positional bias",
    rejection="No held-out gain or unstable across seasons",
    effort="5-8 days",
    horizon="P2",
    scores=dict(rows["AM-ROSTER-12"]["scores"]),
    rescore="Primary AM-ROSTER-12 (68) kept; horizon P3 -> P2 aligned with AM-VALUATION-12 because both lanes target the same BDVM priors.",
    extra_roadmap="#2053 pure-math row 7 (dynasty hazards)",
)

g(
    ["AM-TRADES-15", "AM-ROSTER-10"],
    category="E",
    title="Competitive Posture validation: shadow behavioural check first, posterior-based HOLD later",
    proposed="Does posture predict the next 4 weeks' net buy/sell direction (ordinal agreement, Brier)? Only then replace the perturbation-flip HOLD with a posterior label-probability HOLD using the sim's season-level uncertainty",
    acceptance="Posture agrees with subsequent behaviour above a preregistered baseline; posterior HOLD is not less stable",
    rejection="No behavioural agreement (keep the map, labelled PRIOR)",
    effort="2-3 days check; 3-4 days posterior HOLD",
    horizon="P2",
    scores=dict(rows["AM-ROSTER-10"]["scores"]),
    rescore="Primary score AM-ROSTER-10 (66); the behavioural check (AM-TRADES-15, P2) is sequenced first, so horizon is P2.",
    extra_roadmap="C7-POST-01 (#840)",
)

# ---- rejects merged ------------------------------------------------------------
g(
    ["AM-ROSTER-20", "AM-PROJECTIONS-17"],
    category="REJECT",
    title="REJECT: extreme value theory for IDP splash games, FAAB tails and title-odds tails",
    proposed="None; use empirical quantiles, hurdle counts and order-statistic models",
    mechanism="Too few independent exceedances for a stable GPD shape; top of the dynasty scale is saturated by construction",
    horizon="REJECT",
    rescore="Representative score AM-ROSTER-20 (37).",
    extra_roadmap="#2053 S10; AM-FRONTIER-11 (EVT part)",
)
g(
    ["AM-TRADES-12", "AM-PROJECTIONS-18"],
    category="REJECT",
    title="REJECT: causal DML/TMLE/SCM claims (manager skill, advisor effect, opponent/matchup effects, streaming benefit)",
    proposed="None; keep descriptive realized-value-added and paired contrasts, labelled non-causal",
    mechanism="No exogenous variation, confounding by team strength and window, interference, tiny n; identification fails",
    horizon="REJECT",
    rescore="Representative score AM-TRADES-12 (31).",
    extra_roadmap="#2053 S8; AM-FRONTIER-11 (DML part)",
)

# ---- single-source items (copied) ------------------------------------------------
SINGLES = [
    "AM-ROSTER-04",
    "AM-ROSTER-03",
    "AM-TRADES-09",
    "AM-ROSTER-07",
    "AM-ROSTER-18",
    "AM-TRADES-02",
    "AM-PROJECTIONS-10",
    "AM-FRONTIER-03",
    "AM-PROJECTIONS-08",
    "AM-ROSTER-11",
    "AM-FRONTIER-06",
    "AM-PROJECTIONS-09",
    "AM-PROJECTIONS-11",
    "AM-ROSTER-17",
    "AM-VALUATION-13",
    "AM-FRONTIER-08",
    "AM-PROJECTIONS-06",
    "AM-ROSTER-08",
    "AM-VALUATION-08",
    "AM-VALUATION-11",
    "AM-ROSTER-16",
    "AM-VALUATION-06",
    "AM-TRADES-06",
    "AM-ROSTER-15",
    "AM-FRONTIER-05",
    "AM-VALUATION-10",
    "AM-VALUATION-09",
    "AM-ROSTER-13",
    "AM-TRADES-13",
    "AM-TRADES-14",
    "AM-ROSTER-19",
    "AM-PROJECTIONS-07",
    "AM-TRADES-07",
    "AM-PROJECTIONS-13",
    # blocked
    "AM-VALUATION-07",
    "AM-ROSTER-05",
    "AM-FRONTIER-13",
    "AM-PROJECTIONS-12",
    # keep
    "AM-ROSTER-21",
    "AM-PROJECTIONS-16",
    "AM-PROJECTIONS-15",
    "AM-VALUATION-16",
    "AM-ROSTER-22",
    # reject
    "AM-VALUATION-15",
    "AM-VALUATION-14",
    "AM-FRONTIER-11",
]
SINGLE_OV = {
    "AM-TRADES-09": dict(
        scores=sc(
            advantage=19,
            justification=18,
            data=12,
            feasibility=12,
            strategic=9,
            interpretability=7,
            efficiency=4,
        ),
        rescore="80 -> 81, justification 17 -> 18: the VALUATION lane's independent diagnostic D2 (non-KTC consensus drifts "
        "toward KTC, median Spearman 0.145, positive 9/9 windows; KTC does not drift toward consensus, 0.006) agrees "
        "with this lane's finding of no KTC mean reversion; two separate read-only diagnostics now say the Finder's "
        "implied bet is untested and possibly backwards.",
        extra_roadmap="AM-VALUATION-14 (rejected inefficiency map); VALUATION D2",
    ),
    "AM-FRONTIER-05": dict(
        horizon="P0",
        rescore="Score 69 kept. Horizon P2 -> P0 for the missing-feature -> 0.0 fix only (a MISSING IS NEVER ZERO violation on a "
        "live scoring path, ~1 day, no research); the GMM evidence check stays P2 inside the same row.",
    ),
    "AM-ROSTER-05": dict(
        rescore="Score 58 kept. Supersedes the sequencing of #2053 AMATH-2 / S4: Wasserstein DRO / CVaR streaming is BLOCKED "
        "behind forecast calibration, because the decision layer owns about +3.3 of about +52 hindsight points.",
        extra_roadmap="#2053 AMATH-2 / S4 (superseded sequencing)",
    ),
    "AM-FRONTIER-03": dict(
        rescore="Score 78 kept. Supersedes the method of #2053 AMATH-5: property-based tests (Hypothesis) and exhaustive "
        "enumeration replace CP-SAT / Z3 for these invariants.",
        extra_roadmap="#2053 AMATH-5 (method superseded)",
    ),
    "AM-PROJECTIONS-09": dict(
        extra_roadmap="#2053 S2 (IDP owner retained; this is the offense extension and shared surface)"
    ),
    "AM-PROJECTIONS-10": dict(
        extra_roadmap="#2053 S5 / AMATH-1 (extends missingness to provider non-coverage)"
    ),
    "AM-PROJECTIONS-06": dict(extra_roadmap="#2053 AMATH-4 (input side; frozen ROS H1 untouched)"),
    "AM-PROJECTIONS-07": dict(extra_roadmap="#2053 AMATH-4 (input side; frozen ROS H1 untouched)"),
    "AM-PROJECTIONS-13": dict(
        extra_roadmap="#2053 S7 / AMATH-7 (cheap version; full BMA rejected for one effective family)"
    ),
    "AM-PROJECTIONS-11": dict(
        extra_roadmap="#2053 AMATH-2 (cheap first decision step before any DRO)"
    ),
    "AM-ROSTER-04": dict(extra_roadmap="#2053 AMATH-2 (sub-component, not duplicate)"),
}

# ---------------------------------------------------------------- build
covered: list[str] = []
items: list[dict] = []
for grp in G + [{"ids": [i], **SINGLE_OV.get(i, {})} for i in SINGLES]:
    ids = grp["ids"]
    covered += ids
    prim = rows[ids[0]]
    if len(ids) == 1:
        it = {k: (rr(prim[k]) if k == "related_roadmap" else prim[k]) for k in KEYS}
        it["scores"] = dict(prim["scores"])
    else:
        it = {}
        it["category"] = grp.get("category", prim["category"])
        it["domain"] = uniq_join(rows[i]["domain"] for i in ids)
        it["title"] = grp.get("title", prim["title"])
        for k in [
            "current_system",
            "status",
            "current_method",
            "evidence",
            "baseline",
            "data_available",
            "data_missing",
            "consumers",
            "risk",
        ]:
            it[k] = tagged(ids, k)
        it["code_owner"] = uniq_join(rows[i]["code_owner"] for i in ids)
        it["evidence_class"] = uniq_join(rows[i]["evidence_class"] for i in ids)
        it["principle"] = uniq_join(rows[i]["principle"] for i in ids)
        for k in [
            "proposed",
            "mechanism",
            "evaluation",
            "acceptance",
            "rejection",
            "effort",
            "horizon",
        ]:
            it[k] = grp.get(k, tagged(ids, k) if k not in ("horizon",) else prim[k])
        it["related_roadmap"] = uniq_join(rr(rows[i]["related_roadmap"]) for i in ids)
        it["novelty_note"] = tagged(ids, "novelty_note")
        it["scores"] = dict(prim["scores"])
    for k in [
        "category",
        "title",
        "proposed",
        "mechanism",
        "evaluation",
        "acceptance",
        "rejection",
        "effort",
        "horizon",
    ]:
        if k in grp and len(ids) == 1:
            it[k] = grp[k]
    if grp.get("scores"):
        it["scores"] = dict(grp["scores"])
    if grp.get("extra_roadmap"):
        it["related_roadmap"] = uniq_join([it["related_roadmap"], grp["extra_roadmap"]])
    notes = []
    if len(ids) > 1:
        notes.append(f"MERGED from {', '.join(ids)} (primary {ids[0]}).")
    if grp.get("rescore"):
        notes.append("SCORING: " + grp["rescore"])
    if notes:
        it["novelty_note"] = " ".join(notes) + " LANE NOTES: " + str(it["novelty_note"])
    it["merged_from"] = ids
    s = it["scores"]
    assert s["total"] == sum(s[k] for k in SCORE_KEYS), ids
    items.append(it)

all_ids = set(rows)
assert len(covered) == len(set(covered)), "lane id used twice"
missing = all_ids - set(covered)
assert not missing, missing

HZ = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def bucket(it):
    h = it["horizon"]
    if h == "BLOCKED":
        return 1
    if it["category"] == "REJECT" or h == "REJECT":
        return 3
    if it["category"] == "KEEP" or h == "KEEP":
        return 2
    if h == "BLOCKED":
        return 1
    return 0


items.sort(
    key=lambda it: (
        bucket(it),
        -it["scores"]["total"],
        HZ.get(it["horizon"], 9),
        -len(it["merged_from"]),
        it["merged_from"][0],
    )
)
out = []
for n, it in enumerate(items, 1):
    it["id"] = f"AMATH-S{n:02d}"
    it["final_rank"] = n
    out.append({k: it[k] for k in KEYS + ["merged_from", "final_rank"]})

(EV / "sitewide_opportunities_merged.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
for it in out:
    s = it["scores"]
    print(
        it["id"],
        it["category"],
        it["horizon"],
        s["total"],
        "|",
        it["title"][:80],
        "|",
        ",".join(it["merged_from"]),
    )
print(len(out), "items from", len(covered), "lane rows")
