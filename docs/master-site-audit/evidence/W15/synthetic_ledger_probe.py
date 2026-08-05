"""W15 synthetic-ledger proof harness (scratchpad; writes only to /tmp)."""

from __future__ import annotations
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from src.intel import platform_ledger
from src.sharp import cohort as sharp_cohort
from src.sharp import roster_percentage as rp
from src.sharp import roster_store
from src.sharp import platform_records
from src.sharp import score as sharp_score
from src.platforms.ffpc.identity import resolve_identity

OUT = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/w15"
)
DB = OUT / "synthetic.sqlite3"
if DB.exists():
    DB.unlink()
NOW = int(time.time() * 1000)
conn = platform_ledger.ensure_platform_schema(DB)
roster_store.ensure_roster_schema(conn=conn)
results = {}


def add_manager(key, platform="sleeper", identity="global_verified", canonical=None):
    conn.execute(
        "INSERT OR REPLACE INTO platform_managers (manager_key, platform, source_manager_id,"
        " display_name, source_identity_type, identity_scope, identity_confidence,"
        " canonical_manager_id, first_seen_ms, last_seen_ms)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (key, platform, key.split(":", 1)[1], key, identity, "platform", 1.0, canonical, NOW, NOW),
    )


def add_season(
    key,
    league,
    season,
    wins,
    losses,
    finish,
    teams=12,
    champ=0,
    playoffs=1,
    sharp_eligible=1,
    complete=1,
    identity="global_verified",
):
    conn.execute(
        "INSERT OR REPLACE INTO manager_seasons (league_id, season, user_id, roster_id,"
        " wins, losses, ties, points_for, points_against, made_playoffs, is_champion,"
        " is_runner_up, finish_rank, team_count, is_complete, sharp_eligible, crawled_ms,"
        " platform, league_key, manager_key, source_identity_type, evidence_status,"
        " exclusion_reasons_json, metadata_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            league,
            season,
            key,
            "1",
            wins,
            losses,
            0,
            1500.0,
            1400.0,
            playoffs,
            champ,
            0,
            finish,
            teams,
            complete,
            sharp_eligible,
            NOW,
            key.split(":", 1)[0],
            league,
            key,
            identity,
            "ok",
            "[]",
            "{}",
        ),
    )


def add_trades(key, n, league="lg-A"):
    for i in range(n):
        tx = f"tx-{key}-{i}"
        conn.execute(
            "INSERT OR REPLACE INTO transactions (tx_id, league_id, season, week, tx_type,"
            " status, created_ms, ingested_ms, platform, transaction_key,"
            " source_transaction_id, league_key, metadata_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tx,
                league,
                "2025",
                1,
                "trade",
                "complete",
                NOW - i * 86400000,
                NOW,
                "sleeper",
                tx,
                tx,
                league,
                "{}",
            ),
        )
        mv = f"mv-{key}-{i}"
        conn.execute(
            "INSERT OR REPLACE INTO asset_movements (movement_id, tx_id, league_id, tx_type,"
            " asset_id, asset_type, action, user_id, roster_id, counterparty_user_id, ts,"
            " week, faab_bid, ingested_ms, platform, movement_key, transaction_key,"
            " league_key, canonical_asset_id, source_asset_id, manager_key,"
            " counterparty_manager_key, timestamp_ms, metadata_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mv,
                tx,
                league,
                "trade",
                "4046",
                "player",
                "add",
                key,
                "1",
                None,
                NOW - i * 86400000,
                1,
                None,
                NOW,
                "sleeper",
                mv,
                tx,
                league,
                "4046",
                "4046",
                key,
                None,
                NOW - i * 86400000,
                "{}",
            ),
        )


# ── population: 8 sharp-looking managers, 4 controls ────────────────
CASES = {
    # key: (seasons, wins/season, losses/season, finish_rank, champs)
    "sleeper:elite1": (6, 10, 4, 1, 2),
    "sleeper:elite2": (5, 9, 5, 2, 1),
    "sleeper:elite3": (5, 9, 5, 3, 1),
    "sleeper:good1": (4, 8, 6, 4, 0),
    "sleeper:good2": (4, 8, 6, 5, 0),
    "sleeper:avg1": (3, 7, 7, 6, 0),
    "sleeper:avg2": (3, 7, 7, 7, 0),
    "sleeper:bad1": (3, 6, 8, 10, 0),  # win% .429 -> below 0.52 floor
    "sleeper:onelg": (4, 11, 3, 1, 3),  # only ONE dynasty league
    "sleeper:thin": (1, 12, 2, 1, 1),  # 1 season
    "sleeper:noteligible": (4, 12, 2, 1, 2),  # sharp_eligible=0 rows
}
for key, (seasons, w, ll, finish, champs) in CASES.items():
    add_manager(key)
    leagues = ["lg-A"] if key == "sleeper:onelg" else ["lg-A", "lg-B", "lg-C"]
    n = 0
    for s in range(seasons):
        league = leagues[s % len(leagues)]
        add_season(
            key,
            league,
            str(2020 + s),
            w,
            ll,
            finish,
            champ=1 if n < champs else 0,
            sharp_eligible=0 if key == "sleeper:noteligible" else 1,
        )
        n += 1
    add_trades(key, 12)
conn.commit()

recs, evidence = platform_records.build_manager_records(ledger_path=DB)
scored = sharp_score.score_managers(recs)
results["qualification"] = {
    s.user_id: {
        "evaluable": s.evaluable,
        "score": s.score,
        "pct": s.score_percentile,
        "conf": round(s.confidence, 3),
        "qualified": s.qualified,
        "reasons": s.ineligible_reasons,
    }
    for s in sorted(scored, key=lambda x: x.user_id)
}
results["excluded_managers_with_no_record"] = sorted(set(CASES) - {r.user_id for r in recs})

members, coverage = sharp_cohort.cohort_members(ledger_path=DB)
results["cohort_members"] = sorted(m.manager_key for m in members)
results["cohort_coverage"] = coverage

# ── FFPC name collision path ────────────────────────────────────────
a = resolve_identity(league_id="L1", team_id=None, manager_name="John Smith")
b = resolve_identity(league_id="L2", team_id=None, manager_name="John Smith")
c = resolve_identity(league_id="L1", team_id=None, manager_name="john  smith")
results["ffpc_identity"] = {
    "same_name_diff_league_keys_differ": a.manager_key != b.manager_key,
    "same_name_same_league_keys_match": a.manager_key == c.manager_key,
    "identity_type": a.identity_type,
    "confidence": a.confidence,
    "keys": [a.manager_key, b.manager_key, c.manager_key],
}
# Can a name-only FFPC identity reach automated qualification?
add_manager(a.manager_key, platform="ffpc", identity="name_only")
for s in range(6):
    add_season(a.manager_key, "ffpc:L1", str(2020 + s), 12, 2, 1, champ=1, identity="name_only")
conn.commit()
recs2, ev2 = platform_records.build_manager_records(ledger_path=DB)
scored2 = {s.user_id: s for s in sharp_score.score_managers(recs2)}
results["ffpc_name_only_automated_qualified"] = (
    a.manager_key in scored2 and scored2[a.manager_key].qualified
)
results["ffpc_name_only_evidence_reasons"] = (
    sorted(ev2[a.manager_key].reasons) if a.manager_key in ev2 else None
)

# ── roster percentage: denominator + multi-team dominance ───────────
members, _ = sharp_cohort.cohort_members(ledger_path=DB)
cohort_keys = sorted(m.manager_key for m in members)
whale = cohort_keys[0]
others = cohort_keys[1:]
obs = []
# whale: 5 offense-only rosters, all holding player P_IDP? no — offense only
for i in range(5):
    obs.append(
        roster_store.RosterObservation(
            platform="sleeper",
            league_key=f"whale-lg-{i}",
            manager_key=whale,
            source_roster_id="1",
            observed_ms=NOW,
            league_format={
                "idp": False,
                "kicker": False,
                "teamDefense": False,
                "superflex": True,
                "tePremium": False,
            },
            assets=[roster_store.RosterAsset("4046"), roster_store.RosterAsset("4046")],
        )
    )
# others: one roster each, IDP-enabled, none hold 4046, all hold IDP guy 9999
for j, key in enumerate(others):
    obs.append(
        roster_store.RosterObservation(
            platform="sleeper",
            league_key=f"solo-lg-{j}",
            manager_key=key,
            source_roster_id="1",
            observed_ms=NOW,
            league_format={
                "idp": True,
                "kicker": True,
                "teamDefense": True,
                "superflex": True,
                "tePremium": False,
            },
            assets=[roster_store.RosterAsset("9999")],
        )
    )
roster_store.record_rosters(obs, conn=conn)
conn.commit()

contract = {
    "playersArray": [
        {
            "playerId": "4046",
            "displayName": "Offense Guy",
            "position": "WR",
            "team": "KC",
            "rankDerivedValue": 8000,
            "canonicalConsensusRank": 5,
        },
        {
            "playerId": "9999",
            "displayName": "IDP Guy",
            "position": "LB",
            "team": "SF",
            "rankDerivedValue": 3000,
            "canonicalConsensusRank": 300,
        },
    ]
}
board = rp.build_board(contract=contract, ledger_path=DB, limit=100, now_ms=NOW)
results["board"] = {
    "status": board["status"],
    "players": [
        {
            k: r[k]
            for k in (
                "assetId",
                "displayName",
                "positionFamily",
                "sharpRosters",
                "eligibleRosters",
                "sharpRosterPct",
            )
        }
        for r in board["players"]
    ],
    "transparency": board["transparency"],
    "sample": board["sample"],
    "cohortSelectedManagers": board["cohort"]["selectedManagers"],
}
results["dedup_check_asset_count"] = conn.execute(
    "SELECT COUNT(*) FROM sharp_roster_assets WHERE roster_key LIKE '%whale%'"
).fetchone()[0]
conn.close()
(OUT / "results.json").write_text(json.dumps(results, indent=2, default=str))
print(json.dumps(results, indent=2, default=str)[:9000])
