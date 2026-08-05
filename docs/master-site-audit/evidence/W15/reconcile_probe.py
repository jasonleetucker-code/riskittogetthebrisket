import json
import sys

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from pathlib import Path
from src.sharp import platform_records, score as S

DB = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/w15/synthetic.sqlite3"
)
recs, ev = platform_records.build_manager_records(ledger_path=DB)
by = {r.user_id: r for r in recs}
out = {}

# F00 — rosterQuality inputs never populated by platform_records
out["F00_rosterQuality_inputs"] = {
    k: {
        "roster_value_ratios": v.roster_value_ratios,
        "age_adjusted": v.age_adjusted_value_ratio,
        "depth_adjusted": v.depth_adjusted_value_ratio,
        "pick_capital": v.draft_pick_capital_ratio,
        "abandoned_rosters": v.abandoned_rosters,
    }
    for k, v in list(by.items())[:3]
}
cfg = S.load_config()
pop = S.build_population(recs, cfg)
e1 = by["sleeper:elite1"]
rq, _ = S._roster_quality_component(e1, pop, cfg)
out["F00_rosterQuality_component_value"] = rq
perf, pnotes = S._performance_component(e1, pop, cfg)
cons, cnotes = S._consistency_component(e1, cfg)
lon = S._longevity_component(e1, cfg)
act = S._activity_component(e1, cfg)
pen = S._uncertainty_penalty(e1, cfg)
bonus, bnotes = S._championship_bonus(e1, cfg)
w = cfg["weights"]
total = (
    w["performance"] * perf
    + w["rosterQuality"] * rq
    + w["multiLeagueConsistency"] * cons
    + w["longevity"] * lon
    + w["activity"] * act
    + bonus
) - pen
out["F00_score_decomposition"] = {
    "performance": perf,
    "rosterQuality": rq,
    "consistency": cons,
    "longevity": lon,
    "activity": act,
    "championshipBonus": bonus,
    "uncertaintyPenalty": -pen,
    "weights": w,
    "manual_total_x100": round(min(1.0, max(0.0, total)) * 100, 1),
    "engine_score": [s.score for s in S.score_managers(recs) if s.user_id == "sleeper:elite1"][0],
    "rosterQuality_weight_lost": w["rosterQuality"],
    "max_reachable_score_x100": round(
        (w["performance"] + w["multiLeagueConsistency"] + w["longevity"] + w["activity"]) * 100, 1
    ),
}
# F03 — season rows vs distinct leagues in the consistency term
out["F03_consistency_population"] = {
    "elite1_finish_percentiles_n": len(e1.finish_percentiles),
    "elite1_observed_leagues": e1.observed_leagues,
    "elite1_completed_seasons": e1.completed_seasons,
    "contributor_notes": cnotes,
    "minLeaguesForFullCredit": cfg["multiLeagueConsistency"]["minLeaguesForFullCredit"],
}
# F15 — championship counted twice
out["F15_championship_double_count"] = {
    "in_performance_subweight": cfg["performance"]["subWeights"]["championshipRate"],
    "separate_bonus_applied": bonus,
    "both_nonzero": bonus > 0 and cfg["performance"]["subWeights"]["championshipRate"] > 0,
    "contributor_note": bnotes,
}
# F09 — gates that cannot fire
out["F09_dead_gates"] = {
    "abandoned_rate_all_zero": all(r.abandoned_rate == 0.0 for r in recs),
    "abandoned_rosters_ever_set": any(r.abandoned_rosters for r in recs),
    "maxAbandonedRosterRate": cfg["eligibility"]["maxAbandonedRosterRate"],
    "days_since_last_activity_none_count": sum(
        1 for r in recs if r.days_since_last_activity is None
    ),
    "n_records": len(recs),
}
# F11 — percentile bar with a tiny evaluable population
tiny = [r for r in recs if r.user_id in ("sleeper:elite1", "sleeper:elite2")]
tiny_scored = S.score_managers(tiny)
out["F11_tiny_population"] = {
    "evaluable": sum(1 for s in tiny_scored if s.evaluable),
    "qualified": sum(1 for s in tiny_scored if s.qualified),
    "qualified_share": round(
        sum(1 for s in tiny_scored if s.qualified)
        / max(1, sum(1 for s in tiny_scored if s.evaluable)),
        3,
    ),
    "minScorePercentile": cfg["qualification"]["minScorePercentile"],
    "detail": [
        (s.user_id, s.score, s.score_percentile, s.confidence, s.qualified) for s in tiny_scored
    ],
}
# F12 — how many full re-scores one market request performs
calls = {"n": 0}
orig = platform_records.build_manager_records


def counted(*a, **k):
    calls["n"] += 1
    return orig(*a, **k)


platform_records.build_manager_records = counted
import src.sharp.cohort as C  # noqa: E402

C.platform_records.build_manager_records = counted
from src.sharp import market as M  # noqa: E402

M.market_payload(ledger_path=DB, window="30d")
out["F12_build_manager_records_calls_per_market_request"] = calls["n"]
calls["n"] = 0
from src.sharp import roster_percentage as RP  # noqa: E402

RP.build_board(ledger_path=DB, now_ms=1785883465379)
out["F12_calls_per_roster_percentage_request"] = calls["n"]
platform_records.build_manager_records = orig
C.platform_records.build_manager_records = orig
print(json.dumps(out, indent=2, default=str))
Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/w15/reconcile.json"
).write_text(json.dumps(out, indent=2, default=str))
