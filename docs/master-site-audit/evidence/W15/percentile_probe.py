import json
import sys

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from src.sharp import score as S

cfg = S.load_config()
out = {}
# Controlled population: N evaluable managers with strictly distinct scores.
for n in (2, 3, 4, 5, 8, 20):
    recs = []
    for i in range(n):
        recs.append(
            S.ManagerRecord(
                user_id=f"m{i:02d}",
                completed_seasons=6,
                observed_leagues=4,
                dynasty_leagues=4,
                completed_games=84,
                wins=50 + i,
                losses=34 - i,
                ties=0,
                playoff_appearances=3 + (i % 3),
                championships=i % 3,
                finish_percentiles=[0.5 + 0.02 * i] * 6,
                trades_completed=30,
                days_since_last_activity=10,
            )
        )
    scored = S.score_managers(recs, cfg)
    ev = [s for s in scored if s.evaluable]
    ev.sort(key=lambda s: -(s.score or 0))
    top = ev[0]
    N = len(ev)
    raw_sorted = sorted((s.score for s in ev), reverse=True)
    intended = ((N - 1) + 0.5) / N  # midpoint rule INCLUDING self
    actual = top.score_percentile
    out[f"N={n}"] = {
        "evaluable": N,
        "topScore": top.score,
        "topPercentile_actual": actual,
        "topPercentile_if_self_counted": round(intended, 4),
        "delta": round(intended - (actual or 0), 4),
        "bar": cfg["qualification"]["minScorePercentile"],
        "qualified": sum(1 for s in scored if s.qualified),
        "qualified_share_of_evaluable": round(sum(1 for s in scored if s.qualified) / N, 3),
        "top_clears_bar_actual": (actual or 0) >= cfg["qualification"]["minScorePercentile"],
        "top_clears_bar_if_self_counted": intended >= cfg["qualification"]["minScorePercentile"],
        "scores": raw_sorted[:5],
    }
print(json.dumps(out, indent=2))
