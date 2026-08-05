"""Emit docs/master-site-audit/evidence/registry/W30.jsonl."""

from __future__ import annotations

import json
import pathlib

F: list[dict] = []


def add(**kw):
    kw.setdefault("workstream", "W30")
    kw.setdefault("promptSections", [42, 44])
    F.append(kw)


EV = "docs/master-site-audit/evidence/W30"

add(
    id="W30-F001",
    title="Two playoff-odds engines serve the same /league tab and disagree on the "
    "league's structure: 7 playoff spots vs 6, 12 teams vs 8, and opposite verdicts "
    "for two managers",
    status="Duplicate or conflicting implementation",
    priority="P1",
    size="L",
    subsystem="Playoff odds",
    surface={
        "routes": [
            "/api/public/league/playoffOdds",
            "/api/public/league/rosPlayoffOdds",
        ],
        "pages": ["/league"],
        "flags": ["settings.useRosPlayoffOdds (default true)"],
    },
    codeRefs=[
        {"path": "src/public_league/playoff_odds.py", "lines": "1-60"},
        {"path": "src/ros/playoff_sim.py", "lines": "1-60, 468, 550"},
        {"path": "src/public_league/public_contract.py", "lines": "140-150"},
        {"path": "frontend/components/useSettings.js", "lines": "148"},
    ],
    claimUnderTest="src/ros/playoff_sim.py: 'Outputs match the v1 schema so the "
    "frontend can swap data sources without a contract fork.' public_contract.py: "
    "'Coexists with v1 playoffOdds; frontend swaps via settings.useRosPlayoffOdds.'",
    observed="The two sections do NOT describe the same league. v1 reports "
    "playoffSpots=7 over 12 owners; v2 reports playoffSeeds=6 + byeSeeds=2 over 8 "
    "owners. Four owners present in v1 (Brent, Kich, Blaine, jstuedle) are absent "
    "from v2 entirely. Of the eight owners both engines cover, two flip: Eric and "
    "MaKayla read playoffProbability 0.0 on v1 and playoffOdds 1.0 on v2. A user "
    "toggling one settings switch sees a manager go from 'will miss the playoffs' "
    "to 'certain to make them'.",
    reproduction={
        "command": "for s in playoffOdds rosPlayoffOdds; do curl -s -b "
        '/tmp/audit-cookies.txt "http://127.0.0.1:8000/api/public/league/$s" '
        '-o /tmp/$s.json; done; python -c "import json;'
        "v1=json.load(open('/tmp/playoffOdds.json'))['data'];"
        "v2=json.load(open('/tmp/rosPlayoffOdds.json'))['data'];"
        "print(v1['playoffSpots'],len(v1['owners']),v2['playoffSeeds'],"
        "len(v2['playoffOdds']))\"",
        "expected": "two engines describing one league: identical spot count and "
        "identical owner set",
        "actual": "7 12 6 8",
        "artifact": f"{EV}/playoff-odds-two-engines.json",
    },
    numericProof={
        "inputs": {
            "v1.playoffSpots": 7,
            "v1.ownerCount": 12,
            "v2.playoffSeeds": 6,
            "v2.byeSeeds": 2,
            "v2.ownerCount": 8,
        },
        "formula": "sum(playoffProbability) == playoffSpots",
        "expected": 7,
        "actual": 6,
        "tolerance": 0,
    },
    userImpact="A manager reads the Playoff Odds tab, sees his team at 0% and "
    "starts selling; the other engine says he is a lock. Nothing on the page names "
    "which engine produced the number.",
    blastRadius={"playersAffected": 0, "routesAffected": 2, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A19-F01",
        "relation": "confirmed",
        "note": "prior claimed a team missing from the sim is coerced to 0%; "
        "measured live, v2 omits FOUR of twelve owners. The spot-count disagreement "
        "(7 vs 6) is additional.",
    },
    whatWorks="Both engines run, cache and return well-formed payloads; v1's "
    "probabilities do sum to its own spot count and v2's to its own.",
    rootCause="Two independently-parameterised simulators were allowed to coexist "
    "behind a boolean instead of one engine with a strategy input, so their league "
    "constants (playoff spots, owner set) were never forced to agree.",
    requiredRepair="Derive playoff spots and the owner set from one place for both "
    "engines, and stamp the producing engine on the payload so the UI can name it.",
    dependencies="F002 (both engines are degenerate in preseason regardless)",
)

add(
    id="W30-F002",
    title="Both playoff-odds engines publish 100%/0% certainty with zero games "
    "played and 14 weeks remaining, and the convergence check passes on it",
    status="Implemented but defective",
    priority="P1",
    size="M",
    subsystem="Playoff odds",
    surface={
        "routes": [
            "/api/public/league/playoffOdds",
            "/api/public/league/rosPlayoffOdds",
            "/api/public/league/rosChampionship",
        ],
        "pages": ["/league"],
        "flags": [],
    },
    codeRefs=[
        {"path": "src/public_league/playoff_odds.py", "lines": "1-60"},
        {"path": "src/ros/playoff_sim.py", "lines": "1-60"},
    ],
    claimUnderTest="playoff_odds.py: 'Run N Monte Carlo simulations… sample each "
    "owner's score from their empirical distribution.' The v1 module documents "
    "collapse to 0/1 only for the season-over case ('remaining_weeks == 0').",
    observed="Live payload: weeksPlayed=0, weeksRemaining=14, numSims=10000, "
    "scheduleCertainty='posted', every owner currentWins=0 and currentPointsFor=0.0 "
    "— and every playoffProbability is exactly 1.0 or exactly 0.0. v2 is the same "
    "shape at n_simulations=2000 and reports converged=true with "
    "worstPlayoffOddsSe=0.0: the standard error is zero because every simulation "
    "returns the identical answer, so the convergence gate certifies a degenerate "
    "result. rosChampionship inherits it — Roy shows playoffOdds 1.0, "
    "medianFinalSeed 3 and championshipOdds 0.0 simultaneously.",
    reproduction={
        "command": "curl -s -b /tmp/audit-cookies.txt "
        "'http://127.0.0.1:8000/api/public/league/playoffOdds' | python -c \""
        "import sys,json;d=json.load(sys.stdin)['data'];"
        "print(d['weeksPlayed'],d['weeksRemaining'],d['numSims']);"
        "print(sorted({r['playoffProbability'] for r in d['owners']}))\"",
        "expected": "a spread of probabilities strictly between 0 and 1 with 14 " "weeks unplayed",
        "actual": "0 14 10000 / [0.0, 1.0]",
        "artifact": f"{EV}/playoff-odds-two-engines.json",
    },
    numericProof={
        "inputs": {"weeksPlayed": 0, "weeksRemaining": 14, "numSims": 10000},
        "formula": "count(distinct playoffProbability) over 12 owners",
        "expected": 12,
        "actual": 2,
        "tolerance": 0,
    },
    userImpact="A manager opens /league in August and is told his team has a 0% "
    "chance of making the playoffs before a single snap. Trade-deadline direction "
    "(src/ros/direction.py) reads these same odds, so the same input drives a "
    "'Strong Seller' recommendation.",
    blastRadius={"playersAffected": 0, "routesAffected": 3, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A19-F00",
        "relation": "confirmed",
        "note": "reproduced live with exact payload values; the additional "
        "observation is that v2's convergence gate (converged=true, "
        "worstPlayoffOddsSe=0.0) certifies the degenerate output.",
    },
    whatWorks="scheduleCertainty is reported honestly ('posted'), and both engines "
    "publish weeksPlayed/weeksRemaining so a caller COULD suppress the section.",
    rootCause="With no scored weeks, every owner's empirical distribution is the "
    "same league-wide fallback, so every simulation produces the same standings and "
    "the tie-break (PF, all zero) resolves deterministically.",
    requiredRepair="Refuse to publish odds when weeksPlayed == 0 (the same posture "
    "the codebase uses for unpriced BDVM players), or seed preseason means from a "
    "projection source rather than an empty history.",
    dependencies="",
)

add(
    id="W30-F003",
    title="Two power-ranking engines rank the same league differently on the same "
    "tab — 10 teams vs 12, mean rank shift 2.8, and one manager moves from last to "
    "third",
    status="Duplicate or conflicting implementation",
    priority="P1",
    size="L",
    subsystem="Power rankings",
    surface={
        "routes": ["/api/public/league/power", "/api/public/league/rosPower"],
        "pages": ["/league"],
        "flags": ["settings.useRosPowerRankings (default true)"],
    },
    codeRefs=[
        {"path": "src/public_league/power.py", "lines": "45-47, 141"},
        {"path": "src/ros/power_v2.py", "lines": "65-75, 99-108"},
        {"path": "frontend/app/league/LeagueClient.jsx", "lines": "98-102, 200, 390"},
    ],
    claimUnderTest="public_contract.py: 'ROS-driven power rankings v2. Coexists "
    "with the existing power section above; the frontend swaps between them based "
    "on settings.useRosPowerRankings.'",
    observed="v1 = 100*(0.50*PPG%ile + 0.25*recent%ile + 0.25*allPlayWin%) over 10 "
    "owners. v2 = a 9-component weighted sum over 12 owners, of which SEVEN "
    "components are missing in preseason — the live payload's effectiveWeights are "
    "{team_ros_strength: 0.38, roster_health: 0.03}, i.e. v2 is currently a "
    "renormalised ROS-strength ranking wearing the label 'Power'. Over the 10 teams "
    "both cover, mean |rank shift| is 2.8 and max is 7: Jason is #10 with power 0.0 "
    "on v1 and #3 with 80.69 on v2. Blaine and jstuedle appear only on v2.",
    reproduction={
        "command": "for s in power rosPower; do curl -s -b /tmp/audit-cookies.txt "
        '"http://127.0.0.1:8000/api/public/league/$s" -o /tmp/$s.json; done; '
        'python3 -c "import json;'
        "a={r['displayName']:r['rank'] for r in "
        "json.load(open('/tmp/power.json'))['data']['currentRanking']};"
        "b={r['displayName']:r['rank'] for r in "
        "json.load(open('/tmp/rosPower.json'))['data']['currentRanking']};"
        'print(len(a),len(b));print({k:(a[k],b[k]) for k in a if k in b})"',
        "expected": "one league, one team count, small rank differences",
        "actual": "10 12; Jason (10, 3), Kich (3, 8), Ed (5, 9), Eric (9, 5)",
        "artifact": f"{EV}/power-two-engines.json",
    },
    numericProof={
        "inputs": {"teamsInBoth": 10, "v1Teams": 10, "v2Teams": 12},
        "formula": "mean(|rank_v2 - rank_v1|) over teams present in both",
        "expected": 0,
        "actual": 2.8,
        "tolerance": 0,
    },
    userImpact="A manager reads a Power Rankings table that places him last, "
    "flips one settings toggle, and is third. Neither view states which engine "
    "produced it or that seven of nine v2 components are currently inert.",
    blastRadius={"playersAffected": 0, "routesAffected": 2, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A03-F06",
        "relation": "partial",
        "note": "prior described v1's internal time-scale mixing; this measures the "
        "v1-vs-v2 divergence on the live league and shows v2 running on 2 of 9 "
        "weights.",
    },
    whatWorks="v2 reports missingInputs and effectiveWeights honestly in the "
    "payload, and stamps preseason:true — the data to render a warning exists.",
    rootCause="'Coexists with' was allowed to stand as a design, so two engines "
    "own one product noun with no shared team set, no shared scale and no producer "
    "stamp on the rendered table.",
    requiredRepair="Pick one engine per season phase, or render both side by side "
    "with their names; either way surface missingInputs on the page.",
    dependencies="W30-F004",
)

add(
    id="W30-F004",
    title="Settings default useRosPowerRankings/useRosPlayoffOdds to true while the "
    "code three lines from the read says they are false until validated",
    status="Implemented but defective",
    priority="P2",
    size="XS",
    subsystem="Power rankings",
    surface={
        "routes": [],
        "pages": ["/league", "/settings"],
        "flags": ["useRosPowerRankings", "useRosPlayoffOdds"],
    },
    codeRefs=[
        {"path": "frontend/components/useSettings.js", "lines": "143, 148"},
        {"path": "frontend/app/league/LeagueClient.jsx", "lines": "98-102"},
    ],
    claimUnderTest="LeagueClient.jsx:100 — 'Defaults match the registry in "
    "components/useSettings.js (rosEnabled true, useRosPowerRankings false until "
    "validated per-user).'",
    observed="useSettings.js:143 is `useRosPowerRankings: true` and :148 is "
    "`useRosPlayoffOdds: true`. Every user therefore lands on the unvalidated v2 "
    "engines by default, which is the opposite of what the reader of "
    "LeagueClient.jsx is told.",
    reproduction={
        "command": "grep -n 'useRosPowerRankings\\|useRosPlayoffOdds' "
        "frontend/components/useSettings.js frontend/app/league/LeagueClient.jsx",
        "expected": "the default and the comment agree",
        "actual": "useSettings.js: true / true; LeagueClient.jsx:100 says 'false "
        "until validated per-user'",
        "artifact": f"{EV}/power-two-engines.json",
    },
    numericProof={
        "inputs": {"useRosPowerRankings": True, "useRosPlayoffOdds": True},
        "formula": "documented default == shipped default",
        "expected": 0,
        "actual": 1,
        "tolerance": 0,
    },
    userImpact="Every user sees the v2 engines by default, including the "
    "preseason-degenerate playoff odds, without opting in.",
    blastRadius={"playersAffected": 0, "routesAffected": 2, "pagesAffected": 2},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A03-F07",
        "relation": "confirmed",
        "note": "prior found the /settings hint inverted; the same inversion is "
        "also in the LeagueClient.jsx comment at the read site.",
    },
    whatWorks="Both toggles do switch the fetched section — the wiring is real.",
    rootCause="The default was flipped without updating either the settings hint or "
    "the comment at the consuming site.",
    requiredRepair="Decide the default, then make both comments quote it.",
    dependencies="",
)

add(
    id="W30-F005",
    title="Three Python ports of KTC's Value Adjustment ship simultaneously and one "
    "of them rounds differently; its own parity test's ±1 tolerance is exactly the "
    "size of the divergence",
    status="Duplicate or conflicting implementation",
    priority="P2",
    size="M",
    subsystem="Trade fairness",
    surface={
        "routes": [
            "/api/trade/suggestions",
            "/api/angle/find",
            "/api/trade/finder",
            "/api/trade/simulate-mc",
        ],
        "pages": ["/trade", "/arbitrage", "/angle", "/league"],
        "flags": [],
    },
    codeRefs=[
        {"path": "src/trade/ktc_va.py", "lines": "116, 319"},
        {"path": "src/trade/market_value_adjustment.py", "lines": "33-36, 386"},
        {"path": "src/public_league/trade_grading.py", "lines": "103-112, 387"},
    ],
    claimUnderTest="All three modules claim to be verbatim/line-for-line ports of "
    "frontend/lib/trade-logic.js::ktcAdjustPackage. trade_grading.py:103-112 states "
    "explicitly that Python's builtin round() is round-half-to-even and gives the "
    "wrong answer where JS gives another, and defines _js_round = floor(x+0.5) to "
    "avoid it.",
    observed="src/trade/ktc_va.py — the port used by trade suggestions, the angle "
    "finder and the Monte Carlo sim — still calls Python's round() at :116 "
    "(ktc_reverse_adjust) and :319 (the returned value). The other two ports use "
    "floor(x+0.5). Over 20,000 random packages the ktc_va result differs from "
    "market_value_adjustment on 38 of them (0.19%), always by exactly 1; side and "
    "displayed never differ. ktc_va's own parity test asserts agreement 'to ±1', "
    "so the test cannot fail on this.",
    reproduction={
        "command": '.venv/bin/python -c "import random;'
        "from src.trade.ktc_va import ktc_adjust_package as a;"
        "from src.trade.market_value_adjustment import ktc_adjust_package as b;"
        "random.seed(11);n=0;"
        "\\nfor _ in range(20000):\\n"
        " A=[random.randint(200,9999) for _ in range(random.randint(1,5))];"
        " B=[random.randint(200,9999) for _ in range(random.randint(1,5))];"
        ' n+= int(int(a(A,B).value)!=int(b(A,B).value))\\nprint(n)"',
        "expected": "0",
        "actual": "38",
        "artifact": f"{EV}/ktc-va-three-ports.json",
    },
    numericProof={
        "inputs": {"A": [4581, 6362, 4354], "B": [7181, 3245]},
        "formula": "ktc_adjust_package(A,B).value",
        "expected": 1280,
        "actual": 1281,
        "tolerance": 0,
    },
    userImpact="A package graded on /trade (JS) and the same package graded by "
    "trade suggestions can differ by one point of value adjustment. The magnitude "
    "is tiny; the fact that one algorithm has three maintained copies is not.",
    blastRadius={"playersAffected": 1092, "routesAffected": 4, "pagesAffected": 4},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A02-F09",
        "relation": "confirmed",
        "note": "prior said 'three independent ports with no test tying two of them "
        "together'. Measured: the untied pair diverges on 0.19% of packages, always "
        "by 1, and the rounding function is the cause.",
    },
    whatWorks="Side selection and the display gate agree across all three ports on "
    "all 20,000 trials — the divergence is confined to the final rounding.",
    rootCause="Three ports were written at different times; only two adopted the "
    "JS-rounding shim, and the third's parity test tolerance hides the gap.",
    requiredRepair="Collapse to one port. If that is deferred, at minimum change "
    "ktc_va.py's two round() calls to floor(x+0.5) and tighten its parity "
    "tolerance to 0.",
    dependencies="",
)

add(
    id="W30-F006",
    title="Three call sites in trade suggestions still read the hardcoded "
    "dynasty_main starter demand, so in the 10-team no-IDP league a surplus TE is "
    "detected and then excluded from every sell suggestion",
    status="Implemented but defective",
    priority="P2",
    size="S",
    subsystem="Trade suggestions",
    surface={"routes": ["/api/trade/suggestions"], "pages": ["/trade"], "flags": []},
    codeRefs=[
        {"path": "src/trade/suggestions.py", "lines": "39-47"},
        {"path": "src/trade/suggestions.py", "lines": "882"},
        {"path": "src/trade/suggestions.py", "lines": "921"},
        {"path": "src/trade/suggestions.py", "lines": "1026"},
    ],
    claimUnderTest="suggestions.py:64-71 — 'That model was correct and hardcoded, "
    "which made it silently wrong for any other league… starter counts are "
    "leagueKey-scoped per CLAUDE.md', followed by starter_needs_for_league().",
    observed="starter_needs_for_league('dynasty_new') returns TE:1 (10-team, no "
    "IDP). analyze_roster() honours it, so a 3-TE roster is correctly flagged TE "
    "surplus. But _generate_sell_high (:1026) computes `need = "
    "DEFAULT_STARTER_NEEDS.get(pos, 1)` — 2 for TE — and slices `players[2:]`, so "
    "the TE2 is never a sell candidate in a league that starts one TE. "
    "_generate_sell_high does not even accept a starter_needs argument. rank_score "
    "(:882) and rank_score_breakdown (:921) have the same hardcode, so need-"
    "severity ranking also uses dynasty_main's demand for every league.",
    reproduction={
        "command": '.venv/bin/python -c "from src.trade import suggestions as S;'
        "print(S.starter_needs_for_league('dynasty_new'));"
        "print('hardcoded TE need used inside _generate_sell_high:', "
        "S.DEFAULT_STARTER_NEEDS['TE'])\"",
        "expected": "{'QB':2,'RB':3,'WR':4,'TE':1} / 1",
        "actual": "{'QB': 2, 'RB': 3, 'WR': 4, 'TE': 1} / 2",
        "artifact": f"{EV}/starter-needs-hardcode-repro.json",
    },
    numericProof={
        "inputs": {
            "league": "dynasty_new",
            "rosterTEs": ["Te One 7000", "Te Two 6800", "Te Thr 6600"],
        },
        "formula": "len(players[need:]) where need is the TE starter demand",
        "expected": 2,
        "actual": 1,
        "tolerance": 0,
    },
    userImpact="In the non-default league the engine tells the user he has a TE "
    "surplus and then never offers his second TE in a trade, because the slice "
    "index came from the other league's lineup.",
    blastRadius={"playersAffected": 1092, "routesAffected": 1, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A14-F07",
        "relation": "partial",
        "note": "prior counted 'nine other call sites'. Re-counted at HEAD: of ten "
        "DEFAULT_STARTER_NEEDS references, three are docstrings, three are "
        "legitimate fallbacks (:106, :146, :712) and exactly THREE (:882, :921, "
        ":1026) are unconditional hardcodes on a live path.",
    },
    whatWorks="starter_needs_for_league() itself is correct and reproduces the old "
    "constant for dynasty_main; analyze_roster threads it properly.",
    rootCause="The per-league derivation was added at the entry point but three "
    "helpers that never took the parameter were not converted.",
    requiredRepair="Thread starter_needs into _generate_sell_high, rank_score and "
    "rank_score_breakdown; make DEFAULT_STARTER_NEEDS private to the fallback.",
    dependencies="",
)

add(
    id="W30-F007",
    title="Five incompatible percentile definitions; the one behind Power Rankings "
    "v1 returns a literal 0.0 for the league minimum and the one behind v2 returns "
    "0.0 for an unmeasurable population",
    status="Duplicate or conflicting implementation",
    priority="P2",
    size="M",
    subsystem="Shared math",
    surface={
        "routes": [
            "/api/public/league/power",
            "/api/public/league/rosPower",
            "/api/sharp/cohort",
            "/api/gameplan",
        ],
        "pages": ["/league", "/market/sharp-tracker"],
        "flags": [],
    },
    codeRefs=[
        {"path": "src/public_league/power.py", "lines": "52-61"},
        {"path": "src/sharp/score.py", "lines": "191-203"},
        {"path": "src/ros/power_v2.py", "lines": "99-108"},
        {"path": "src/roster_intel/window.py", "lines": "228-231, 238-241"},
        {"path": "src/roster_intel/profiles.py", "lines": "86-89"},
    ],
    claimUnderTest="docs/audits/formula-registry.json percentile-helper: 'canonical: "
    "NONE — five incompatible definitions', status documented-divergence.",
    observed="Confirmed and quantified. On a 12-value population: power.py returns "
    "0.0 for the minimum and 1.0 for the maximum; sharp/score.py, ros/power_v2.py "
    "and the two inline copies in roster_intel/window.py all return 0.0417 and "
    "0.9583 for the same inputs. On an EMPTY population power.py and sharp both "
    "return 0.5 (neutral) while ros/power_v2.py returns 0.0 — an unmeasurable "
    "percentile reads as worst-in-league. window.py writes the sharp formula out "
    "twice inline rather than importing it. profiles.py:89 is not a percentile at "
    "all but a banker's-rounded index, `vals[max(0, round(n*0.05)-1)]`, whose index "
    "steps non-monotonically with n.",
    reproduction={
        "command": '.venv/bin/python -c "'
        "from src.public_league.power import _percentile_rank as a;"
        "from src.sharp.score import percentile_rank as b;"
        "from src.ros.power_v2 import _percentile as c;"
        "p=[10,20,30,40,50,60,70,80,90,100,110,120];"
        "print(a(p,120), b(120,p), c(p,120));"
        'print(a([],5), b(5,[]), c([],5))"',
        "expected": "one definition, one answer",
        "actual": "1.0 0.9583333333333334 0.9583333333333334 / 0.5 0.5 0.0",
        "artifact": f"{EV}/percentile-helpers.json",
    },
    numericProof={
        "inputs": {
            "population": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120],
            "target": 120,
        },
        "formula": "percentile_rank(target, population)",
        "expected": 0.958333,
        "actual": 1.0,
        "tolerance": 0.0001,
    },
    userImpact="The last-place team on /league Power Rankings v1 scores exactly "
    "0.0 rather than a small positive number, which reads as 'no measurable "
    "strength' rather than 'lowest of twelve'. Live payload confirms it: Jason, "
    "power = 0.0.",
    blastRadius={"playersAffected": 0, "routesAffected": 4, "pagesAffected": 2},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A09-F09",
        "relation": "new",
        "note": "the formula registry names this divergence in prose; this finding "
        "attaches the numbers and adds that window.py duplicates the sharp formula "
        "inline twice rather than importing it.",
    },
    whatWorks="Every helper is internally consistent and each is documented at its " "own site.",
    rootCause="No shared percentile utility exists, so each subsystem wrote its "
    "own tie and empty-population convention.",
    requiredRepair="One helper with an explicit empty-population policy; import it "
    "everywhere including the two inline copies in window.py.",
    dependencies="W30-F003",
)

add(
    id="W30-F008",
    title="Hill curves are fitted on percentiles over a 400-row denominator and "
    "served on a 500-row one, so the same rank is worth up to 25% more at serve "
    "time than the fit ever saw",
    status="Implemented but defective",
    priority="P1",
    size="L",
    subsystem="Value pipeline",
    surface={"routes": ["/api/data"], "pages": ["/rankings"], "flags": []},
    codeRefs=[
        {"path": "src/model_registry/holdout.py", "lines": "81-85, 145"},
        {"path": "src/api/data_contract.py", "lines": "5297-5303"},
        {"path": "src/canonical/player_valuation.py", "lines": "371"},
    ],
    claimUnderTest="holdout.py:81-83 — 'The fit truncates every source to its top "
    "400 before computing percentiles. Matched exactly so train and holdout RMSE "
    "are the same quantity measured on different data.' The match is between train "
    "and holdout; nothing matches either to SERVING.",
    observed="The fit maps native rank i to p = i/(n-1) with n capped at "
    "FIT_TOP_N = 400, i.e. a denominator of 399. Serving maps rank to "
    "p = (rank-1)/(_PERCENTILE_REFERENCE_N - 1) = (rank-1)/499. The same rank "
    "therefore lands at a smaller percentile at serve time and, under the fitted "
    "Hill V(p) = 9999/(1+(p/c)^s), at a HIGHER value than any observation the fit "
    "was scored against. With the champion OFFENSE constants (c=0.11, s=1.11): "
    "rank 50 serves 13.2% high, rank 100 18.5% high, rank 400 25.4% high.",
    reproduction={
        "command": '.venv/bin/python -c "'
        "from src.model_registry.holdout import hill, FIT_TOP_N;"
        "from src.canonical.player_valuation import HILL_PERCENTILE_C as C, "
        "HILL_PERCENTILE_S as S;"
        "from src.api.data_contract import _PERCENTILE_REFERENCE_N as R;"
        "f=lambda r: hill((r-1)/(FIT_TOP_N-1),C,S);"
        "g=lambda r: hill((r-1)/(R-1),C,S);"
        "print([(r, round(f(r),1), round(g(r),1), round(100*(g(r)-f(r))/f(r),2)) "
        'for r in (50,100,200,400)])"',
        "expected": "identical percentile denominators, so 0% difference",
        "actual": "[(50, 4694.3, 5314.0, 13.2), (100, 2884.2, 3419.0, 18.54), "
        "(200, 1573.6, 1931.3, 22.73), (400, 794.3, 995.8, 25.37)]",
        "artifact": f"{EV}/percentile-train-serve-skew.json",
    },
    numericProof={
        "inputs": {
            "rank": 100,
            "c": 0.11,
            "s": 1.11,
            "fitDenominator": 399,
            "serveDenominator": 499,
        },
        "formula": "V(p) = 9999 / (1 + (p/c)^s)",
        "expected": 2884.2,
        "actual": 3419.0,
        "tolerance": 1.0,
    },
    userImpact="Every value on /rankings past the top handful is produced by a "
    "curve evaluated outside the coordinate system it was scored in. The holdout "
    "RMSE that gates promotion (787.84 for the champion) is therefore not a "
    "measurement of the served board's error.",
    blastRadius={"playersAffected": 1092, "routesAffected": 1, "pagesAffected": 1},
    confidence="medium",
    priorFinding={
        "match": "PRIOR-A13-F08",
        "relation": "new",
        "note": "the formula registry names 'TRAIN/SERVE SKEW, open' for "
        "percentile-reference without a magnitude. This attaches one. Confidence is "
        "medium rather than high because serving normalises POST-LADDER effective "
        "ranks, so the arithmetic is exact only for sources whose ladder is near "
        "identity — KTC, the very source _PERCENTILE_REFERENCE_N=500 was chosen to "
        "align with.",
    },
    whatWorks="Train and holdout ARE matched to each other, as the docstring "
    "claims, and the champion's params match the committed constants exactly.",
    rootCause="FIT_TOP_N and _PERCENTILE_REFERENCE_N are two independent constants "
    "with no assertion tying them together.",
    requiredRepair="Either fit at 500 or serve at 400; add a test that imports both "
    "constants and asserts they agree.",
    dependencies="",
)

add(
    id="W30-F009",
    title="docs/audits/formula-registry.json covers 16 concepts against 126 "
    "formulas found at HEAD and omits every duplicate this workstream measured",
    status="Partially implemented",
    priority="P2",
    size="M",
    subsystem="Documentation / governance",
    surface={"routes": [], "pages": [], "flags": []},
    codeRefs=[
        {"path": "docs/audits/formula-registry.json", "lines": "1-end"},
        {"path": "tests/audit/test_formula_registry.py", "lines": "76-140"},
    ],
    claimUnderTest="test_formula_registry.py — 'its value is not the document — it "
    "is that a new duplicate implementation of an already-owned concept shows up as "
    "a diff against this file instead of as a bug report months later.'",
    observed="The registry holds 16 concepts. A full pass over src/ and "
    "frontend/lib produced 126 formulas (W30 formula-inventory.csv), 70 of them "
    "carrying a duplicate-of pointer and 32 of them verdicted 'Duplicate or "
    "conflicting implementation'. Concepts with two or more live implementations that "
    "the registry does not mention at all: playoff odds (2 engines), championship "
    "odds, power rankings (2 engines), replacement level (4), contender/rebuilder "
    "(6), best-ball/team-value (3, of which only 'team-value' is partly recorded), "
    "detect_tiers (2), Buy/Sell/Hold producers (5 — the registry records this "
    "concept with duplicates: []), movers (2), confidence (3), positional need (2). "
    "The registry's checks are file-existence and four spot invariants; nothing "
    "detects an unregistered concept.",
    reproduction={
        "command": '.venv/bin/python -c "import json,csv;'
        "r=json.load(open('docs/audits/formula-registry.json'));"
        "rows=list(csv.DictReader(open("
        "'docs/master-site-audit/evidence/W30/formula-inventory.csv')));"
        "print(len(r['concepts']), len(rows), "
        "sum(1 for x in rows if x['duplicate-of'] not in ('-','')))\"",
        "expected": "registry concept count comparable to the formula census",
        "actual": "16 126 70",
        "artifact": f"{EV}/formula-inventory.csv",
    },
    numericProof={
        "inputs": {
            "registryConcepts": 16,
            "formulasFound": 126,
            "formulasWithADuplicatePointer": 70,
        },
        "formula": "concepts recorded / concepts with more than one implementation",
        "expected": 16,
        "actual": 5,
        "tolerance": 0,
    },
    userImpact="None directly. The cost is that the mechanism intended to make a "
    "new duplicate show up as a diff cannot see 11 of the concepts that already "
    "have one.",
    blastRadius={"playersAffected": 0, "routesAffected": 0, "pagesAffected": 0},
    confidence="high",
    priorFinding={
        "match": None,
        "relation": "new",
        "note": "no prior finding " "mentions the formula registry.",
    },
    whatWorks="Every one of the 16 recorded concepts is accurate about the "
    "implementations it names, the four spot invariants really are enforced, and "
    "the REMOVED-marker check genuinely catches resurrection.",
    rootCause="The registry is hand-maintained with no census step, so it grows "
    "only when someone remembers to add to it.",
    requiredRepair="Add the 11 missing concepts; add a test that fails when a "
    "module defines a function whose name matches an existing canonical entry.",
    dependencies="W30-F010",
)

add(
    id="W30-F010",
    title="Two formula-registry duplicate entries name constructs that no longer "
    "exist, and the test that guards the registry only checks that FILES exist",
    status="Deprecated but still active",
    priority="P3",
    size="XS",
    subsystem="Documentation / governance",
    surface={"routes": [], "pages": [], "flags": []},
    codeRefs=[
        {"path": "docs/audits/formula-registry.json", "lines": "starter-slots entry"},
        {"path": "tests/audit/test_formula_registry.py", "lines": "112-133"},
    ],
    claimUnderTest="The starter-slots entry lists three live divergent duplicates: "
    "src/trade/suggestions.py::DEFAULT_STARTER_NEEDS (DL/LB/DB=3), "
    "frontend/lib/league-analysis.js::STARTER_SLOTS (DL/LB/DB=2) and "
    "frontend/lib/portfolio-insights.js::defaultSlots.",
    observed="league-analysis.js::STARTER_SLOTS exists only inside a comment at "
    ":48 describing the constant that was removed; portfolio-insights.js has no "
    "defaultSlots at all. Both were replaced by the shared "
    "frontend/lib/starter-slots.js. The registry still presents them as live "
    "divergences. test_consumer_and_live_duplicate_paths_resolve only asserts that "
    "the named FILE exists, so a stale construct name inside an existing file "
    "passes.",
    reproduction={
        "command": "grep -n 'STARTER_SLOTS' frontend/lib/league-analysis.js; "
        "grep -c 'defaultSlots' frontend/lib/portfolio-insights.js; "
        ".venv/bin/python -m pytest tests/audit/test_formula_registry.py -q",
        "expected": "a live constant in each file, or a failing registry test",
        "actual": "line 48 is a comment; 0 matches; 11 passed",
        "artifact": f"{EV}/dead-code-map.csv",
    },
    numericProof={
        "inputs": {"registryLiveDuplicatesClaimed": 3, "actuallyPresent": 1},
        "formula": "count of named duplicate constructs still in the tree",
        "expected": 3,
        "actual": 1,
        "tolerance": 0,
    },
    userImpact="None. A future reader is told a divergence exists that was fixed.",
    blastRadius={"playersAffected": 0, "routesAffected": 0, "pagesAffected": 0},
    confidence="high",
    priorFinding={"match": None, "relation": "new", "note": ""},
    whatWorks="The REMOVED-disposition path DOES check for the construct rather "
    "than the file (removedMarker); only the non-REMOVED path is file-only.",
    rootCause="Fixing the duplicate did not include updating the registry, and the "
    "test cannot detect that.",
    requiredRepair="Give every duplicate entry a marker literal and check for it, "
    "the same way REMOVED entries already are.",
    dependencies="W30-F009",
)

add(
    id="W30-F011",
    title="src/api/chat.py ships a documented private endpoint that is never "
    "registered — /api/chat returns 404 on the running server",
    status="Scaffolded only",
    priority="P3",
    size="XS",
    subsystem="Dead code",
    surface={"routes": ["/api/chat"], "pages": [], "flags": []},
    codeRefs=[{"path": "src/api/chat.py", "lines": "3, 215"}],
    claimUnderTest="src/api/chat.py:3 — 'Single private endpoint (/api/chat) gated "
    "by the existing…'",
    observed="No module in src/, server.py or scripts/ imports src.api.chat; the "
    "module declares no router and nothing calls add_api_route for it. /api/chat is "
    "absent from evidence/openapi.json's 100 live operations and both GET and POST "
    "return 404 against the running server.",
    reproduction={
        "command": "curl -s -o /dev/null -w '%{http_code}\\n' -b "
        "/tmp/audit-cookies.txt http://127.0.0.1:8000/api/chat; "
        "grep -rn 'api.chat\\|from src.api import chat' --include=*.py src/ server.py",
        "expected": "200 or 401, and at least one importer",
        "actual": "404, and no importer",
        "artifact": f"{EV}/module-reachability.json",
    },
    numericProof={
        "inputs": {"route": "/api/chat"},
        "formula": "HTTP status of GET /api/chat",
        "expected": 401,
        "actual": 404,
        "tolerance": 0,
    },
    userImpact="None — nothing calls it. The cost is a maintained module that "
    "documents itself as a live endpoint.",
    blastRadius={"playersAffected": 0, "routesAffected": 1, "pagesAffected": 0},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A10-F15",
        "relation": "confirmed",
        "note": "prior counted eleven decision-support modules with authoritative "
        "docstrings and no importer; the reachability closure here puts the total "
        "at 30 of 300 src modules unreachable from server.py, scripts/ or the "
        "scraper.",
    },
    whatWorks="The module imports cleanly and its tests pass.",
    rootCause="Route registration was never added, and no test asserts the route " "exists.",
    requiredRepair="Register it or remove it; either way the docstring must stop "
    "claiming a live endpoint.",
    dependencies="",
)

add(
    id="W30-F012",
    title="src/news/unified_signal_engine.py calls itself the single entry point "
    "for every BUY/SELL/HOLD decision emitted to users and has zero importers, "
    "while five other producers ship",
    status="Scaffolded only",
    priority="P2",
    size="M",
    subsystem="Buy/Sell signals",
    surface={
        "routes": [
            "/api/terminal",
            "/api/bdvm/values",
            "/api/sharp/market",
            "/api/consensus-edge/top",
        ],
        "pages": ["/", "/rankings", "/bdvm", "/market/sharp-tracker"],
        "flags": [],
    },
    codeRefs=[
        {"path": "src/news/unified_signal_engine.py", "lines": "1-30"},
        {"path": "src/api/terminal.py", "lines": "875"},
        {"path": "frontend/lib/signal-engine.js", "lines": "29-47"},
        {"path": "src/bdvm/market.py", "lines": "307-351"},
        {"path": "src/consensus_edge/score.py", "lines": "326-333"},
    ],
    claimUnderTest="unified_signal_engine.py:1 — 'Unified signal engine — single "
    "entry point for every BUY/SELL/HOLD decision emitted to users.'",
    observed="Nothing imports it. Meanwhile five independent Buy/Sell producers do "
    "ship, with three different label vocabularies: terminal.py::_evaluate_signal "
    "and signal-engine.js (RISK/SELL/MONITOR/STRONG_HOLD/BUY/HOLD, parity-pinned to "
    "each other), bdvm/market.py (STRONG_BUY..STRONG_SELL/NO_MARKET), "
    "consensus_edge/score.py (Strong Buy/Buy/Sell/Strong Sell on a -100..100 "
    "composite) and sharp/market.py (cohort net movement). The formula registry "
    "records buy-sell-hold with duplicates: [].",
    reproduction={
        "command": "grep -rn 'import.*unified_signal_engine' --include=*.py src/ "
        "server.py scripts/ | grep -v '^src/news/unified_signal_engine.py'; "
        "echo 'exit'$?",
        "expected": "at least one importer for the claimed single entry point",
        "actual": "no import line; the only occurrences anywhere are four "
        "comments (src/api/feature_flags.py:75,78,332 and "
        "src/consensus_edge/__init__.py:7) that describe it as NOT wired",
        "artifact": f"{EV}/module-reachability.json",
    },
    numericProof={
        "inputs": {"claimedEntryPoints": 1},
        "formula": "count of live BUY/SELL/HOLD producers",
        "expected": 1,
        "actual": 5,
        "tolerance": 0,
    },
    userImpact="A player can carry a HOLD on /rankings, a STRONG_SELL on /bdvm and "
    "a Buy on /consensus-edge simultaneously, with no shared vocabulary and nothing "
    "on any page saying the three are different questions.",
    blastRadius={"playersAffected": 1092, "routesAffected": 4, "pagesAffected": 4},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A18-F13",
        "relation": "partial",
        "note": "prior covered the two parity-pinned engines' divergent inputs; "
        "this adds that the module claiming to unify them is unreachable and that "
        "there are five producers, not two.",
    },
    whatWorks="The two engines that ARE pinned (terminal.py and signal-engine.js) "
    "genuinely share tests/fixtures/signal_parity_cases.json, and BDVM deliberately "
    "keeps a separate label set and a separate user_kv namespace so the two alert "
    "streams cannot collide.",
    rootCause="A unification was designed and built but never wired, and the "
    "concepts kept multiplying afterwards.",
    requiredRepair="Either wire it or delete it; then record buy-sell-hold in the "
    "formula registry with its real duplicate list.",
    dependencies="W30-F009",
)

add(
    id="W30-F013",
    title="src/api/auction_power.py has no Python caller; the file that calls "
    "itself a 'JS mirror' of it is the only live implementation",
    status="Scaffolded only",
    priority="P3",
    size="XS",
    subsystem="Dead code",
    surface={"routes": ["/api/draft-capital"], "pages": ["/draft"], "flags": []},
    codeRefs=[
        {"path": "src/api/auction_power.py", "lines": "1-170"},
        {"path": "frontend/lib/auction-power.js", "lines": "1-11"},
    ],
    claimUnderTest="frontend/lib/auction-power.js:1 — 'Effective auction power — JS "
    "mirror of src/api/auction_power.py… see that module's docstring for the…'",
    observed="The only reference to src/api/auction_power.py anywhere outside its "
    "own file and its tests is that comment. The 'mirror' is the original as far as "
    "production is concerned.",
    reproduction={
        "command": "grep -rn 'auction_power' --include=*.py --include=*.js src/ "
        "server.py frontend/lib/ frontend/app/ | grep -v '^src/api/auction_power.py'",
        "expected": "a Python importer",
        "actual": "one comment in frontend/lib/auction-power.js",
        "artifact": f"{EV}/dead-code-map.csv",
    },
    numericProof={
        "inputs": {"module": "src/api/auction_power.py"},
        "formula": "count of production importers",
        "expected": 1,
        "actual": 0,
        "tolerance": 0,
    },
    userImpact="None directly; a maintainer changing the Python file to fix a "
    "number on /draft would change nothing.",
    blastRadius={"playersAffected": 0, "routesAffected": 1, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A00-F14",
        "relation": "confirmed",
        "note": "also matches PRIOR-A10-F14 and PRIOR-A12-F23; reproduced by " "grep at HEAD.",
    },
    whatWorks="The JS implementation is live and tested.",
    rootCause="A backend implementation was ported to the client and the original "
    "was left in place labelled as the source of truth.",
    requiredRepair="Delete the Python module or make the JS import from an endpoint "
    "that serves it. Update the JS header either way.",
    dependencies="",
)

add(
    id="W30-F014",
    title="CLAUDE.md's adapter table claims scraper_bridge_adapter.py is live in "
    "server.py; it has no production caller, and docs/ONBOARDING.md points at a "
    "path that does not exist",
    status="Scaffolded only",
    priority="P3",
    size="XS",
    subsystem="Adapters",
    surface={"routes": [], "pages": [], "flags": []},
    codeRefs=[
        {"path": "src/adapters/scraper_bridge_adapter.py", "lines": "1-end"},
        {"path": "CLAUDE.md", "lines": "895"},
        {"path": "docs/ONBOARDING.md", "lines": "44"},
    ],
    claimUnderTest="CLAUDE.md:895 — '| scraper_bridge_adapter.py | live "
    "(server.py) |'. docs/ONBOARDING.md:44 — 'Wire the new source into the scraper "
    "bridge (src/adapters/scraper_bridge.py).'",
    observed="ScraperBridgeAdapter is referenced only by tests and by "
    "src/adapters/__init__.py (which server.py triggers transitively when it "
    "imports sleeper_trending, so the module is imported but never constructed). "
    "src/adapters/scraper_bridge.py does not exist at all, so ONBOARDING sends a "
    "new contributor to a missing file.",
    reproduction={
        "command": "grep -rn 'scraper_bridge' --include=*.py src/ server.py scripts/ "
        "| grep -v '^src/adapters/'; ls src/adapters/scraper_bridge.py",
        "expected": "a construction site in server.py, and the ONBOARDING path " "existing",
        "actual": "no non-test construction; ls: No such file or directory",
        "artifact": f"{EV}/dead-code-map.csv",
    },
    numericProof={
        "inputs": {"class": "ScraperBridgeAdapter"},
        "formula": "count of production instantiations",
        "expected": 1,
        "actual": 0,
        "tolerance": 0,
    },
    userImpact="None at runtime. A contributor following ONBOARDING to add a source "
    "edits a file that is not there.",
    blastRadius={"playersAffected": 0, "routesAffected": 0, "pagesAffected": 0},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A24-F14",
        "relation": "confirmed",
        "note": "reproduced; the ONBOARDING.md stale path is additional.",
    },
    whatWorks="src/adapters/base.py really is the frozen contract imported by tests "
    "only, exactly as CLAUDE.md says; sleeper_trending and ktc_crowd_faab really "
    "are live.",
    rootCause="Source ingestion moved into Dynasty Scraper.py + scripts/ fetchers "
    "and the adapter table was not updated.",
    requiredRepair="Correct the CLAUDE.md row to match base.py's ('tests only') and "
    "fix the ONBOARDING path.",
    dependencies="",
)

add(
    id="W30-F015",
    title="Five of the seven functions in src/canonical/calibration.py, including "
    "the whole legacy pick curve and calibrate_canonical_values, have zero "
    "production references and are held alive by their own tests",
    status="Scaffolded only",
    priority="P3",
    size="S",
    subsystem="Dead code",
    surface={"routes": [], "pages": [], "flags": []},
    codeRefs=[{"path": "src/canonical/calibration.py", "lines": "159, 356"}],
    claimUnderTest="docs/audits/formula-registry.json pick-value lists "
    "src/canonical/calibration.py::_pick_curve_value as 'LEGACY, not live'; "
    "src/canonical/__init__.py describes calibration as 'legacy display-scale "
    "helpers; to_display_value is consumed by src.trade.suggestions'.",
    observed="Symbol-by-symbol scan over src/, server.py and scripts/: "
    "to_display_value has 3 production references and _is_pick has 18; "
    "_parse_pick_info, _pick_curve_value, _build_legacy_pick_lookup, "
    "calibrate_canonical_values and get_calibration_params have ZERO. The registry "
    "records the pick curve but not that the entire calibration entry point is "
    "dead.",
    reproduction={
        "command": "for f in _parse_pick_info _pick_curve_value "
        "_build_legacy_pick_lookup calibrate_canonical_values "
        'get_calibration_params; do echo -n "$f "; grep -rn "$f" --include=*.py '
        "src/ server.py scripts/ | grep -vc 'src/canonical/calibration.py'; done",
        "expected": ">=1 for each",
        "actual": "0 for all five",
        "artifact": f"{EV}/dead-code-map.csv",
    },
    numericProof={
        "inputs": {"functionsInModule": 7},
        "formula": "count with at least one production reference",
        "expected": 7,
        "actual": 2,
        "tolerance": 0,
    },
    userImpact="None. The cost is a 'legacy' label on a module that is 5/7 dead "
    "and 2/7 load-bearing, which makes it dangerous to delete wholesale.",
    blastRadius={"playersAffected": 0, "routesAffected": 0, "pagesAffected": 0},
    confidence="high",
    priorFinding={"match": None, "relation": "new", "note": ""},
    whatWorks="to_display_value is genuinely live and correctly documented as such "
    "in src/canonical/__init__.py.",
    rootCause="The canonical-build path was retired but its calibration module was "
    "kept because two helpers in it were still needed.",
    requiredRepair="Move to_display_value and _is_pick out, then remove the rest.",
    dependencies="",
)

add(
    id="W30-F016",
    title="'Contender' is computed six different ways across six surfaces, from "
    "four unrelated input families",
    status="Duplicate or conflicting implementation",
    priority="P2",
    size="L",
    subsystem="Team classification",
    surface={
        "routes": [
            "/api/gameplan",
            "/api/bdvm/roster",
            "/api/trade/suggestions",
            "/api/public/league/rosTradeDeadline",
        ],
        "pages": ["/phases", "/rosters", "/league", "/bdvm", "/trade"],
        "flags": [],
    },
    codeRefs=[
        {"path": "frontend/lib/team-phase.js", "lines": "79-92"},
        {"path": "src/ros/direction.py", "lines": "53-100"},
        {"path": "src/roster_intel/window.py", "lines": "85-104"},
        {"path": "src/bdvm/roster.py", "lines": "63-95"},
        {"path": "src/trade/suggestions.py", "lines": "803-808"},
        {"path": "frontend/lib/league-analysis.js", "lines": "1146-1152"},
    ],
    claimUnderTest="The prior audit's registry counts three team-phase classifiers.",
    observed="Six. (1) team-phase.js: 4 labels from a median split on top-25 value "
    "x median age. (2) ros/direction.py: 7 labels from playoff + championship odds "
    "with position-aware veteran ages. (3) roster_intel/window.py: 5 states as a "
    "softmax over (competitiveness, trajectory) at temperature 0.18. (4) "
    "bdvm/roster.py: 3 labels from a league-relative now/future capital ratio. (5) "
    "trade/suggestions.py:803: 3 labels per PLAYER from years_exp. (6) "
    "league-analysis.js:1146: 3 labels from a hard tercile of a roster score. Some "
    "of the divergence is legitimate — a player-level tag is not a team classifier "
    "— but at least four of the six answer the same question about the same team "
    "with different math and different label counts.",
    reproduction={
        "command": "grep -rln 'contend\\|rebuild' --include=*.py --include=*.js "
        "src/ frontend/lib/ | xargs grep -ln 'def classify\\|classifyPhase\\|"
        "_directions_relative\\|_strategy_for_player\\|tier: i <'",
        "expected": "one classifier",
        "actual": "six modules define one",
        "artifact": f"{EV}/formula-inventory.csv",
    },
    numericProof={
        "inputs": {"priorAuditCount": 3},
        "formula": "count of independent contender/rebuilder classifiers at HEAD",
        "expected": 3,
        "actual": 6,
        "tolerance": 0,
    },
    userImpact="A manager can be 'Win-now' on /phases, 'rebuild' on /api/gameplan, "
    "'Strong Seller' on the /league deadline tab and 'Mid-Tier' on /rosters at the "
    "same moment.",
    blastRadius={"playersAffected": 0, "routesAffected": 4, "pagesAffected": 5},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A18-F00",
        "relation": "confirmed",
        "note": "prior found /phases and /api/gameplan giving opposite labels for "
        "one team. Independently recounted: six classifiers, not three.",
    },
    whatWorks="roster_intel/window.py is the most defensible of the six — it "
    "publishes a probability distribution rather than a label and states its own "
    "ordering caveat. bdvm/roster.py documents why it went league-relative.",
    rootCause="Each surface needed a phase label and none of them found an existing "
    "one it could reuse across units (board value vs odds vs FPG vs capital ratio).",
    requiredRepair="Nominate one classifier per unit family and have the others "
    "consume it; record the concept in the formula registry.",
    dependencies="W30-F009",
)

add(
    id="W30-F017",
    title="Team total value is computed three ways and the two simple sums differ "
    "by pick capital — 22.5% of a portfolio on the live snapshot",
    status="Duplicate or conflicting implementation",
    priority="P2",
    size="M",
    subsystem="Roster strength",
    surface={"routes": ["/api/terminal"], "pages": ["/", "/rosters"], "flags": []},
    codeRefs=[
        {"path": "src/api/terminal.py", "lines": "1070, 1204-1221"},
        {"path": "frontend/lib/league-analysis.js", "lines": "1100-1140"},
        {"path": "src/roster_intel/marginal.py", "lines": "136-138"},
    ],
    claimUnderTest="terminal.py's own comment at :1204-1221 records the divergence "
    "and calls it 'a known difference instead of a claimed equivalence'.",
    observed="Confirmed at HEAD. /api/terminal's totalValue sums player values "
    "only; frontend/lib/portfolio-insights.js and league-analysis.js sum players "
    "AND resolved picks. The in-code measurement is 442,936 of pick value against "
    "1,524,591 of player value on the live 12-team snapshot — 22.5% of a portfolio. "
    "A third definition, roster_intel/marginal.py, is lineup-constrained and in "
    "different units entirely (ROS points).",
    reproduction={
        "command": "sed -n '1200,1225p' src/api/terminal.py",
        "expected": "one team-value definition",
        "actual": "the comment documents two, differing by 442,936 of 1,967,527",
        "artifact": f"{EV}/formula-inventory.csv",
    },
    numericProof={
        "inputs": {"pickValue": 442936, "playerValue": 1524591},
        "formula": "pickValue / (pickValue + playerValue)",
        "expected": 0.0,
        "actual": 0.225,
        "tolerance": 0.005,
    },
    userImpact="The Total Value tile on the home terminal and the same team's total "
    "on /rosters can differ by nearly a quarter with no note on either surface.",
    blastRadius={"playersAffected": 1092, "routesAffected": 1, "pagesAffected": 2},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A18-F10",
        "relation": "confirmed",
        "note": "prior found PortfolioSummary showing a picks-excluding Total Value "
        "beside a legend that includes them.",
    },
    whatWorks="The divergence is documented in code with a real measurement, and "
    "the formula registry records it as documented-divergence.",
    rootCause="Two independent sums grew on two surfaces; the client's pick join "
    "was broken, which made the outputs agree while the intents did not, and fixing "
    "the join exposed it.",
    requiredRepair="Label the tile ('players only') or include picks in both.",
    dependencies="",
)

add(
    id="W30-F018",
    title="The market corridor clamp justifies itself by naming a mechanism that no "
    "longer exists in the tree",
    status="Deprecated but still active",
    priority="P3",
    size="XS",
    subsystem="Value pipeline",
    surface={"routes": ["/api/data"], "pages": ["/rankings"], "flags": []},
    codeRefs=[{"path": "src/api/data_contract.py", "lines": "4670-4690"}],
    claimUnderTest="data_contract.py:4688 — the clamp's comment justifies it as "
    "containing 'the IDP calibration runaway'.",
    observed="_apply_idp_calibration_post_pass and config/idp_calibration.json are "
    "both absent from the tree (CLAUDE.md records the removal). The clamp still "
    "runs on every IDP row and still does real work against raw blend drift, but "
    "its stated reason for existing is a retired mechanism, so a future reader "
    "cannot tell whether removing it is safe.",
    reproduction={
        "command": "grep -rn '_apply_idp_calibration_post_pass' --include=*.py src/ "
        "server.py; ls config/idp_calibration.json; sed -n '4686,4692p' "
        "src/api/data_contract.py",
        "expected": "the named mechanism exists",
        "actual": "no matches under src/ or server.py (only "
        "tests/api/test_valuation_pipeline_stages.py:586 asserting its absence); "
        "No such file or directory; the comment still cites it",
        "artifact": f"{EV}/formula-inventory.csv",
    },
    numericProof={
        "inputs": {"clampBandCap": 0.15, "assetClass": "idp"},
        "formula": "count of live implementations of the cited mechanism",
        "expected": 1,
        "actual": 0,
        "tolerance": 0,
    },
    userImpact="None directly. It makes the clamp un-removable without re-deriving " "its purpose.",
    blastRadius={"playersAffected": 1092, "routesAffected": 1, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": None,
        "relation": "new",
        "note": "CLAUDE.md already flags the stale rationale; this "
        "confirms it at the code site.",
    },
    whatWorks="The clamp itself is correct and bounded (P90 band, hard cap 0.15, "
    "min bucket n=30, IDP only).",
    rootCause="The post-pass was deleted; the comment that referenced it was not.",
    requiredRepair="Re-derive and restate the clamp's justification against raw "
    "blend drift, or measure whether it still changes any row.",
    dependencies="",
)

add(
    id="W30-F019",
    title="TE premium uses a measured curve for base→TE++ and a flat 1.10 prior for "
    "TEP-native sources, so one concept has two maths decided by source class",
    status="Duplicate or conflicting implementation",
    priority="P2",
    size="M",
    subsystem="TE correction",
    surface={
        "routes": ["/api/data"],
        "pages": ["/rankings"],
        "flags": ["RISKIT_FEATURE_TE_BASIS_CONVERSION"],
    },
    codeRefs=[
        {"path": "src/league_intel/te_premium.py", "lines": "323-355"},
        {"path": "src/api/data_contract.py", "lines": "5909-5911"},
    ],
    claimUnderTest="CLAUDE.md step 5a — 'Replaces a flat 1.15 that sat below the "
    "entire observed range… TEP-native sources keep the flat 1.10 — only base ↔ "
    "tepp is measured.'",
    observed="Accurately documented, and still a divergence: a TE row's premium is "
    "1.209-2.053 (measured, and a function of the TE's own base VALUE rather than "
    "his rank) or exactly 1.10 (a prior) depending only "
    "on which source published it. The measured range does not contain 1.10 at any "
    "rank, so the two paths cannot agree anywhere on the board. A second unresolved "
    "half is stated in CLAUDE.md itself: the target basis is a constant, but TE "
    "demand is a leagueKey property and the two live leagues on "
    "superflex_tep15_ppr1 want different bases.",
    reproduction={
        "command": '.venv/bin/python -c "from src.league_intel.te_premium import '
        "tep_uplift, load_tep_curve; print(load_tep_curve()); "
        'print([(v, round(tep_uplift(v),3)) for v in (9000,3000,1500,600,300)])"',
        "expected": "a measured multiplier whose range includes the flat 1.10 used "
        "for TEP-native sources",
        "actual": "(a=43.555794, k=0.632839, floor=1.209206, ceiling=2.0531); "
        "[(9000, 1.209), (3000, 1.275), (1500, 1.426), (600, 1.76), (300, 2.053)]",
        "artifact": f"{EV}/formula-inventory.csv",
    },
    numericProof={
        "inputs": {"flatTepNativeMultiplier": 1.10, "measuredCurveMin": 1.209},
        "formula": "measured uplift at the top of the board",
        "expected": 1.10,
        "actual": 1.209,
        "tolerance": 0.0,
    },
    userImpact="Two sources ranking the same TE identically contribute different "
    "values to the blend purely because of their declared basis.",
    blastRadius={"playersAffected": 1092, "routesAffected": 1, "pagesAffected": 1},
    confidence="medium",
    priorFinding={
        "match": None,
        "relation": "new",
        "note": "the registry records te-premium as 'corrected' with "
        "duplicates: []; the TEP-native flat path is not listed.",
    },
    whatWorks="The double-count guard is structural (from==to is a no-op, verified "
    "by tests/audit/test_formula_registry.py) and ktc/ktcSfTep are exempt because "
    "the anchor IS the TE++ board.",
    rootCause="No measurement exists for TEP-native → TE++, so the old prior was "
    "left in place when the base path was replaced.",
    requiredRepair="Measure it, or state on the methodology panel that TE values "
    "from TEP-native sources carry a prior rather than a measurement.",
    dependencies="",
)

add(
    id="W30-F020",
    title="Two functions named detect_tiers implement different math; the "
    "script-only one is gated by a feature flag the codebase itself marks as "
    "gating nothing",
    status="Duplicate or conflicting implementation",
    priority="P3",
    size="S",
    subsystem="Tiering",
    surface={"routes": ["/api/data"], "pages": ["/rankings"], "flags": ["positional_tiers"]},
    codeRefs=[
        {"path": "src/canonical/player_valuation.py", "lines": "202"},
        {"path": "src/scoring/tiering.py", "lines": "201, 226"},
        {"path": "src/api/feature_flags.py", "lines": "72, 410"},
    ],
    claimUnderTest="feature_flags.py:410 — positional_tiers is listed under NO_GATE, "
    "i.e. the flag controls nothing.",
    observed="src/canonical/player_valuation.py::detect_tiers (rolling-median gap) "
    "is live via data_contract.py:2033. src/scoring/tiering.py::detect_tiers "
    "(pool-normalized effect size with grid-searched thresholds and drift "
    "detection) is called only by scripts/refit_tier_thresholds.py. Same name, "
    "different algorithm, different consumers, and the flag that nominally chooses "
    "between them gates nothing.",
    reproduction={
        "command": "grep -rn 'def detect_tiers' --include=*.py src/; "
        "grep -rn 'detect_tiers(' --include=*.py src/ server.py scripts/ | "
        "grep -v 'def '",
        "expected": "one definition",
        "actual": "two definitions; the canonical one called from data_contract.py"
        ":2033, the scoring one only from within its own module and the refit script",
        "artifact": f"{EV}/dead-code-map.csv",
    },
    numericProof={
        "inputs": {"functionName": "detect_tiers"},
        "formula": "count of definitions in src/",
        "expected": 1,
        "actual": 2,
        "tolerance": 0,
    },
    userImpact="None today. A maintainer told to 'fix tiering' has a 50% chance of "
    "editing the one that is not live.",
    blastRadius={"playersAffected": 1092, "routesAffected": 1, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A09-F10",
        "relation": "confirmed",
        "note": "prior said config/tiers/thresholds.json and src/scoring/tiering.py "
        "are wired to nothing; confirmed, and the name collision is additional.",
    },
    whatWorks="The live detect_tiers is genuinely reachable and tested.",
    rootCause="A replacement tiering algorithm was built beside the incumbent under "
    "the same name and never swapped in.",
    requiredRepair="Rename one, and either wire the effect-size version or record "
    "it in the registry as the deliberate offline tool it is.",
    dependencies="W30-F009",
)

add(
    id="W30-F021",
    title="REFUTED at HEAD: scoreTeamTiers' pick term no longer has a net positive "
    "sign — picks now cost 0.1 per unit exactly as documented",
    status="Implemented and verified",
    priority="P3",
    size="XS",
    subsystem="Roster strength",
    surface={"routes": [], "pages": ["/rosters"], "flags": []},
    codeRefs=[{"path": "frontend/lib/league-analysis.js", "lines": "1055-1080, 1131"}],
    claimUnderTest="PRIOR-A03-F00 — 'scoreTeamTiers' pick term has the wrong net "
    "sign: draft picks INCREASE a team's contender score by +0.1 per unit, while "
    "the UI tells the user they are penalised.'",
    observed="Fixed at HEAD, and the fix is documented in place at :1072-1079 as "
    "'math audit 2026-08-04, H5'. depthValue is now `totalValue - starterValue - "
    "pickValue`, so pick capital is excluded from the +0.2 depth term and pays only "
    "the -0.1 pick term. Net coefficient on a pick dollar: -0.1, matching the "
    "docstring's 'penalized at −10% (rebuild signal)'.",
    reproduction={
        "command": "sed -n '1129,1133p' frontend/lib/league-analysis.js",
        "expected": "depthValue excluding picks and a negative pick term",
        "actual": "const depthValue = totalValue - starterValue - pickValue; "
        "const score = starterValue * 0.7 + depthValue * 0.2 + "
        "(pickValue > 0 ? -pickValue * 0.1 : 0);",
        "artifact": f"{EV}/formula-inventory.csv",
    },
    numericProof={
        "inputs": {"pickValue": 1000, "starterValue": 0, "totalValue": 1000},
        "formula": "0.7*starterValue + 0.2*(total - starter - pick) - 0.1*pick",
        "expected": -100.0,
        "actual": -100.0,
        "tolerance": 0.0,
    },
    userImpact="None — this records that a previously-reported defect is closed, so "
    "it is not re-opened by the merge.",
    blastRadius={"playersAffected": 0, "routesAffected": 0, "pagesAffected": 1},
    confidence="high",
    priorFinding={
        "match": "PRIOR-A03-F00",
        "relation": "refuted",
        "note": "the sign is correct at HEAD; the prior finding describes the "
        "pre-2026-08-04 code.",
    },
    whatWorks="All of it. The fix also carries its own explanation of the defect it "
    "closed, which is why it was verifiable in one read.",
    rootCause="n/a",
    requiredRepair="none",
    dependencies="",
)

add(
    id="W30-F022",
    title="30 of 300 src modules are unreachable from server.py, scripts/ or the "
    "scraper, and 27 more are script-only",
    status="Scaffolded only",
    priority="P3",
    size="L",
    subsystem="Dead code",
    surface={"routes": [], "pages": [], "flags": []},
    codeRefs=[
        {"path": "src/league_intel/sim.py", "lines": "1"},
        {"path": "src/league_intel/twin.py", "lines": "1"},
        {"path": "src/trade/correlation_matrix.py", "lines": "1"},
        {"path": "src/nfl_data/freshness.py", "lines": "1"},
        {"path": "src/roster_intel/roster_source.py", "lines": "1"},
        {"path": "src/ros/tags.py", "lines": "1"},
    ],
    claimUnderTest="Every one of these modules carries a docstring describing live " "behaviour.",
    observed="AST import closure from server.py (absolute, relative and "
    "importlib.import_module edges, package __init__ normalised) reaches 243 of 300 "
    "src modules. 27 are reachable only from scripts/ — legitimate for the refit, "
    "crawl and fetch tooling. 30 are reachable from nothing: notably "
    "src/api/chat.py, src/api/auction_power.py, src/api/espn_schema_drift.py, "
    "src/news/unified_signal_engine.py, src/trade/correlation_matrix.py, "
    "src/league_intel/{sim,twin,calibration}.py, src/backtesting/harness.py, "
    "src/canonical/{confidence_intervals,rank_history_band}.py, "
    "src/nfl_data/{freshness,injury_feed,opportunity_stats,usage_windows,"
    "reception_shape_projection}.py, src/platforms/sleeper.py, "
    "src/roster_intel/roster_source.py, src/ros/tags.py, src/bdvm/backtest.py. "
    "The freshness guard is a live-looking safety rail that no live path consults: "
    "its only importer is src/news/usage_signals.py, whose only importer is a "
    "script.",
    reproduction={
        "command": '.venv/bin/python -c "import json;'
        "d=json.load(open('docs/master-site-audit/evidence/W30/"
        "module-reachability.json'));"
        "print(d['srcModules'], d['reachableFromServer'], len(d['scriptOnly']), "
        "len(d['neither']))\"",
        "expected": "few or no unreachable modules",
        "actual": "300 243 27 30",
        "artifact": f"{EV}/module-reachability.json",
    },
    numericProof={
        "inputs": {"srcModules": 300},
        "formula": "modules reachable from server.py / scripts/ / Dynasty Scraper.py",
        "expected": 300,
        "actual": 270,
        "tolerance": 0,
    },
    userImpact="None at runtime. The cost is that ~10% of the Python surface reads "
    "as production and is not, which is how PRIOR-A10-F15's 'authoritative "
    "docstrings, zero importers' problem keeps recurring.",
    blastRadius={"playersAffected": 0, "routesAffected": 0, "pagesAffected": 0},
    confidence="medium",
    priorFinding={
        "match": "PRIOR-A10-F15",
        "relation": "confirmed",
        "note": "prior counted eleven such modules; the full closure puts it at 30. "
        "Confidence is medium because a module loaded purely by a runtime string not "
        'matching importlib.import_module("…") would be a false positive — the '
        "src/ros/sources/* family was caught this way and excluded.",
    },
    whatWorks="src/ros/sources/* IS dynamically loaded by module-path string and is "
    "correctly live; the analysis was corrected to exclude it.",
    rootCause="Modules are added for planned features and left in place when the " "wiring slips.",
    requiredRepair="Run this closure in CI and require a new unreachable module to "
    "carry an explicit marker.",
    dependencies="W30-F011, W30-F012, W30-F013",
)

out = pathlib.Path("docs/master-site-audit/evidence/registry/W30.jsonl")
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as fh:
    for f in F:
        fh.write(json.dumps(f, ensure_ascii=False) + "\n")
print(f"wrote {out}  findings={len(F)}")
by_p: dict[str, int] = {}
by_s: dict[str, int] = {}
for f in F:
    by_p[f["priority"]] = by_p.get(f["priority"], 0) + 1
    by_s[f["status"]] = by_s.get(f["status"], 0) + 1
print(json.dumps({"byPriority": by_p, "byStatus": by_s}, indent=1))
