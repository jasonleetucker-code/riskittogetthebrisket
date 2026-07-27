"""Worked examples for the dynasty valuation framework.

NOTE: the player pool used to derive replacement levels is SYNTHETIC (a smooth
rank-decay curve per position, calibrated to plausible 12-team Superflex/TEP/PPR
+ balanced-IDP scoring). Swap in the real projection file and every number below
recomputes. The 13 players are hypothetical archetypes, not real people.
"""
from dynasty_engine import (
    LeagueConfig, ReplacementEngine, synthetic_pool, DynastyModel, Player,
    RiskProfile, package_value, trade_verdict, pick_value, roster_report,
    STRATEGIES,
)

cfg = LeagueConfig()

POOL = {
    "QB": synthetic_pool(24.0, 0.020),
    "RB": synthetic_pool(20.0, 0.028),
    "WR": synthetic_pool(19.0, 0.024),
    "TE": synthetic_pool(16.0, 0.045),
    "DL": synthetic_pool(16.0, 0.030),
    "LB": synthetic_pool(19.0, 0.018),
    "DB": synthetic_pool(14.0, 0.020),
}

repl = ReplacementEngine(cfg, POOL)
print("=" * 78)
print("REPLACEMENT LEVELS   (12-tm SF / TEP / PPR / IDP  — synthetic pool)")
print("=" * 78)
for g in ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]:
    print(f"  {g:>3}  startable slots league-wide: {repl.counts.get(g,0):>3}"
          f"   replacement FPG: {repl.R(g):6.2f}")

players = [
    Player("p1", "Young elite QB (dual)", "QB", 24.0, 3, 22.5, 16.5, 0.9, "dual",
           career_load=1150, kappa=0.06,
           risk=RiskProfile(0.92, 0.95, 0.85, 0.70, 1.8, 0.8, 0.08, 0.28, 0.0),
           market_value=9400, market_dispersion=0.12),
    Player("p2", "Aging productive QB (pocket)", "QB", 34.0, 12, 19.0, 16.0, 0.7, "pocket",
           career_load=6200, kappa=0.0,
           risk=RiskProfile(0.88, 0.80, 0.55, 0.62, 1.0, 0.7, 0.10, 0.25, 0.0),
           market_value=3600, market_dispersion=0.30),
    Player("p3", "Young RB, three-down", "RB", 23.0, 2, 15.5, 15.5, 1.1, None,
           career_load=310, kappa=0.18,
           risk=RiskProfile(0.80, 0.85, 0.80, 0.65, 1.1, 0.7, 0.15, 0.35, 0.0),
           market_value=7400, market_dispersion=0.22),
    Player("p4", "Aging RB, heavy mileage", "RB", 29.0, 8, 14.5, 15.0, 1.3, None,
           career_load=1720, kappa=0.0,
           risk=RiskProfile(0.72, 0.70, 0.35, 0.45, 0.9, 0.6, 0.20, 0.35, 0.0),
           market_value=2200, market_dispersion=0.34),
    Player("p5", "Young ascending WR", "WR", 23.0, 2, 14.0, 16.0, 1.4, None,
           career_load=140, kappa=0.30,
           risk=RiskProfile(0.72, 0.88, 0.85, 0.70, 0.7, 0.7, 0.22, 0.30, 0.0),
           market_value=7900, market_dispersion=0.26),
    Player("p6", "Veteran WR, stable role", "WR", 30.0, 9, 15.5, 16.0, 0.8, None,
           career_load=980, kappa=0.0,
           risk=RiskProfile(0.86, 0.70, 0.60, 0.68, 1.2, 0.7, 0.10, 0.28, 0.0),
           market_value=4100, market_dispersion=0.28),
    Player("p7", "Young TE, year-2 leap", "TE", 24.0, 2, 10.5, 16.0, 1.2, None,
           career_load=95, kappa=0.28,
           risk=RiskProfile(0.70, 0.80, 0.85, 0.70, 0.6, 0.7, 0.25, 0.35, 0.0),
           market_value=5600, market_dispersion=0.30),
    Player("p8", "Elite EDGE rusher", "EDGE", 26.0, 5, 14.5, 16.0, 0.9, None,
           career_load=2600, kappa=0.04,
           risk=RiskProfile(0.90, 0.90, 0.80, 0.68, 1.6, 0.8, 0.08, 0.55, 0.0),
           market_value=6200, market_dispersion=0.35),
    Player("p9", "Three-down LB, green dot", "LB", 25.0, 3, 17.5, 16.5, 0.8, None,
           career_load=2100, kappa=0.08,
           risk=RiskProfile(0.92, 0.75, 0.75, 0.72, 1.4, 0.85, 0.07, 0.20, 0.05),
           market_value=5400, market_dispersion=0.32),
    Player("p10", "Volatile boundary CB", "CB", 26.0, 4, 9.0, 16.0, 1.1, "boundary",
           career_load=2500, kappa=0.0,
           risk=RiskProfile(0.70, 0.65, 0.55, 0.62, 0.3, 0.6, 0.35, 0.70, 0.0),
           market_value=1800, market_dispersion=0.45),
    Player("p11", "Box safety, tackle floor", "S", 27.0, 5, 11.5, 16.0, 0.7, "box",
           career_load=2900, kappa=0.0,
           risk=RiskProfile(0.85, 0.55, 0.60, 0.70, 0.9, 0.65, 0.12, 0.25, 0.35),
           market_value=2600, market_dispersion=0.38),
    Player("p12", "Rookie WR, 1st-rd capital", "WR", 22.0, 1, 9.0, 15.0, 2.2, None,
           career_load=0, kappa=0.55,
           risk=RiskProfile(0.55, 0.95, 0.90, 0.60, -0.4, 0.6, 0.55, 0.35, 1.0),
           market_value=6800, market_dispersion=0.40),
    Player("p13", "Late-round breakout WR", "WR", 25.0, 3, 13.0, 16.0, 1.6, None,
           career_load=330, kappa=0.10,
           risk=RiskProfile(0.62, 0.15, 0.45, 0.66, 0.6, 0.6, 0.35, 0.35, 0.0),
           market_value=3900, market_dispersion=0.42),
]

model = DynastyModel(cfg, repl, stud_gamma=1.20, pool=POOL)
model.calibrate(players, target=9800.0)
vals = [model.value(p) for p in players]

print()
print("=" * 118)
print("WORKED EXAMPLES — fundamental trade values by strategy profile (0–10,000 scale)")
print("=" * 118)
hdr = (f"{'Player':<30}{'Pos':>4}{'Age':>5}{'FPG':>6}{'VORG':>7}"
       f"{'CONT':>7}{'BAL':>7}{'REBLD':>7}{'MKT':>7}{'GAP':>7}{'BLEND':>7}")
print(hdr)
print("-" * 118)
for v in vals:
    print(f"{v.name:<30}{v.pos:>4}{v.raw['age']:>5.0f}{v.raw['fpg']:>6.1f}"
          f"{v.raw['vorg']:>7.2f}"
          f"{v.trade_value['contender']:>7.0f}{v.trade_value['balanced']:>7.0f}"
          f"{v.trade_value['rebuilder']:>7.0f}"
          , end="")
    mv = next(p.market_value for p in players if p.player_id == v.player_id)
    print(f"{mv:>7.0f}{v.market_gap:>7.0f}{v.blended_value:>7.0f}")

print()
print("=" * 118)
print("PROBABILITY OUTPUTS")
print("=" * 118)
print(f"{'Player':<30}{'P(>repl)':>10}{'P(elite)':>10}{'P(start 3y)':>13}"
      f"{'P(breakout)':>13}{'P(collapse 1y)':>16}")
print("-" * 118)
for v in vals:
    p = v.probs
    print(f"{v.name:<30}{p['p_above_replacement']:>10.2f}{p['p_elite_season']:>10.2f}"
          f"{p['p_starter_in_3y']:>13.2f}{p['p_breakout']:>13.2f}"
          f"{p['p_value_collapse_1y']:>16.2f}")

print()
print("=" * 118)
print("VALUE DECOMPOSITION (balanced profile)")
print("=" * 118)
print(f"{'Player':<30}{'yr0':>8}{'yr1-2':>8}{'yr3+':>8}{'surv drag':>12}"
      f"{'5y traj':>12}{'age_eff':>9}")
print("-" * 118)
for v in vals:
    e = v.explain
    print(f"{v.name:<30}{e['year_0_share']:>8.0%}{e['years_1_2_share']:>8.0%}"
          f"{e['years_3_plus_share']:>8.0%}{e['survival_drag']:>12.0%}"
          f"{e['traj_5y']:>+12.0%}{v.raw['age_eff']:>9.1f}")

print()
print("=" * 78)
print("SEASON PATH — Young RB vs Aging RB (balanced horizon)")
print("=" * 78)
for v in [vals[2], vals[3]]:
    print(f"\n{v.name}:")
    print(f"   {'t':>2}{'age':>6}{'age_eff':>9}{'muFPG':>8}{'sigma':>7}"
          f"{'SSV':>9}{'S(t)':>7}{'E[val]':>9}")
    for r in v.seasons[:7]:
        print(f"   {int(r['t']):>2}{r['age']:>6.0f}{r['age_eff']:>9.1f}{r['mu']:>8.2f}"
              f"{r['sigma']:>7.2f}{r['ssv']:>9.1f}{r['survival']:>7.2f}{r['expected']:>9.1f}")

print()
print("=" * 78)
print("SCARCITY DEMO — LB vs S (the 'more points ≠ more value' requirement)")
print("=" * 78)
print(f"  LB replacement {repl.R('LB'):.2f} FPG | DB replacement {repl.R('DB'):.2f} FPG")
print(f"  Three-down LB @17.5 FPG -> VORG {17.5-repl.R('LB'):.2f}"
      f"  | trade value {vals[8].trade_value['balanced']:.0f}")
print(f"  Box safety    @11.5 FPG -> VORG {11.5-repl.R('DB'):.2f}"
      f"  | trade value {vals[10].trade_value['balanced']:.0f}")
mid_lb = 12.5
print(f"  Mid LB        @{mid_lb} FPG -> VORG {mid_lb-repl.R('LB'):.2f}"
      f"  (scores MORE than the safety, is worth LESS)")

print()
print("=" * 78)
print("TRADE MATH — 2-for-1 consolidation (theta=1.20)")
print("=" * 78)
young_wr = vals[4].trade_value["balanced"]
vet_wr = vals[5].trade_value["balanced"]
young_te = vals[6].trade_value["balanced"]
print(f"  Side A: young ascending WR ({young_wr:.0f})")
print(f"  Side B: veteran WR ({vet_wr:.0f}) + young TE ({young_te:.0f}) "
      f"= naive sum {vet_wr+young_te:.0f}")
tv = trade_verdict([young_wr], [vet_wr, young_te], spots_available=2)
print(f"  CES package value   A={tv['side_a']:.0f}  B={tv['side_b']:.0f}"
      f"  edge to A: {tv['edge']:+.0f} ({tv['edge_pct']:+.1f}%)")
tv2 = trade_verdict([young_wr], [vet_wr, young_te], spots_available=1)
print(f"  Same trade, receiving team has 1 open roster spot: "
      f"B={tv2['side_b']:.0f} (roster-spot charge applied)")

print()
print("=" * 78)
print("ROOKIE PICKS")
print("=" * 78)
for slot in [1, 3, 6, 12, 16, 24, 36]:
    for strat in ["contender", "balanced", "rebuilder"]:
        pv = pick_value(slot, class_strength=1.0, years_out=0, strategy=strat)
        if strat == "balanced":
            bal = pv
        if strat == "contender":
            con = pv
        if strat == "rebuilder":
            reb = pv
    print(f"  pick {slot:>2}: contender {con['ev']:>6.0f} | balanced {bal['ev']:>6.0f}"
          f" | rebuilder {reb['ev']:>6.0f} | P(hit) {bal['p_hit']:.2f}"
          f" | ceiling {bal['ceiling']:.0f}")
nxt = pick_value(6, class_strength=0.9, years_out=1, strategy="rebuilder")
print(f"  next-year pick ~1.06, weak class (0.9x), rebuilder: {nxt['ev']:.0f}")

print()
print("=" * 78)
print("ROSTER REPORT — sample 13-player roster")
print("=" * 78)
rep = roster_report(vals, cfg)
for k, v in rep.items():
    print(f"  {k}: {v}")
