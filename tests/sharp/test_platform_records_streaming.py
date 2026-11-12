"""WA-17 — ``build_manager_records`` streams the season rows.

Production's ``manager_seasons`` holds about 1.14 million rows.  The former
builder ``fetchall()``-ed every one (with every column value) before folding
them, and the 2026-11-12 peak heap census counted 1,138,004 live
``sqlite3.Row`` objects in a burst of about 19 million Python objects.  The
builder now folds each row into per-manager totals as the cursor yields it.

Three groups of proofs:

* parity — on seeded, deliberately messy ledgers the streamed builder returns
  exactly what the retired algorithm returned (kept verbatim below as the
  oracle): the same records in the same order and the same evidence;
* memory — on a production-shaped ledger, the streamed builder's traced
  peak per row is a fraction of the retired one's;
* single-flight — concurrent cache misses in ``cohort_members`` share one
  computation (and its failure) instead of each building its own copy.
"""

from __future__ import annotations

import json
import random
import threading
import time
import tracemalloc
from typing import Any

import pytest

from src.intel import platform_ledger
from src.platforms.base import IDENTITY_GLOBAL_VERIFIED
from src.sharp import cohort, platform_records
from src.sharp import score as sharp_score

NOW_S = 1_800_000_000.0
DAY_MS = 86_400_000

# ── the retired algorithm, verbatim (the oracle) ─────────────────────


def _legacy_row_reasons(row: Any) -> list[str]:
    reasons: list[str] = []
    identity_type = str(row["source_identity_type"] or "")
    if identity_type != IDENTITY_GLOBAL_VERIFIED:
        reasons.append(
            "league_scoped_identity"
            if identity_type in ("league_scoped_team", "name_only")
            else "insufficient_multi_league_identity"
        )
    if not row["is_complete"]:
        reasons.append("missing_completed_season")
    if not row["sharp_eligible"]:
        reasons.append("unknown_or_ineligible_league_format")
    for result_field in platform_records._REQUIRED_RESULT_FIELDS:
        if row[result_field] is None:
            reasons.append(
                "missing_playoff_result"
                if result_field in ("made_playoffs", "is_champion")
                else f"missing_{result_field}"
            )
    try:
        stored = json.loads(row["exclusion_reasons_json"] or "[]")
    except (TypeError, ValueError):
        stored = []
    reasons.extend(str(value) for value in stored if str(value).strip())
    return list(dict.fromkeys(reasons))


def _legacy_build_manager_records(*, ledger_path=None, min_season_rows: int = 1):
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        rows = conn.execute(
            """
            SELECT ms.*, COALESCE(pm.platform, ms.platform, 'sleeper') AS source_platform,
                   COALESCE(pm.source_identity_type, ms.source_identity_type,
                            'global_verified') AS resolved_identity_type
              FROM manager_seasons ms
              LEFT JOIN platform_managers pm ON pm.manager_key=ms.manager_key
            """
        ).fetchall()
        activity = {
            str(r["manager_key"]): int(r["n"] or 0)
            for r in conn.execute(
                """
                SELECT manager_key, COUNT(DISTINCT transaction_key) AS n
                  FROM asset_movements
                 WHERE tx_type='trade' AND manager_key IS NOT NULL
                 GROUP BY manager_key
                """
            ).fetchall()
        }
        last_seen = {
            str(r["manager_key"]): int(r["ts"])
            for r in conn.execute(
                """
                SELECT manager_key, MAX(ts) AS ts
                  FROM asset_movements
                 WHERE manager_key IS NOT NULL
                 GROUP BY manager_key
                """
            ).fetchall()
            if r["ts"] is not None
        }
    finally:
        conn.close()

    evidence: dict[str, platform_records.EvidenceStatus] = {}
    eligible_by_manager: dict[str, list[Any]] = {}
    for row in rows:
        key = str(row["manager_key"] or "")
        if not key:
            continue
        platform = str(row["source_platform"] or key.split(":", 1)[0])
        status = evidence.setdefault(key, platform_records.EvidenceStatus(key, platform))
        status.total_rows += 1
        data = dict(row)
        data["source_identity_type"] = row["resolved_identity_type"]
        reasons = _legacy_row_reasons(data)
        if platform == "ffpc" and key not in last_seen:
            reasons.append("missing_recent_activity")
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            status.reasons.update(reasons)
            continue
        status.automated_eligible_rows += 1
        eligible_by_manager.setdefault(key, []).append(row)

    now_ms = int(time.time() * 1000)
    records: list[sharp_score.ManagerRecord] = []
    for manager_key, seasons in eligible_by_manager.items():
        if len(seasons) < min_season_rows:
            continue
        leagues = {str(s["league_key"] or s["league_id"]) for s in seasons}
        wins = sum(int(s["wins"]) for s in seasons)
        losses = sum(int(s["losses"]) for s in seasons)
        ties = sum(int(s["ties"]) for s in seasons)
        finishes = [
            (int(s["team_count"]) - int(s["finish_rank"])) / float(int(s["team_count"]) - 1)
            for s in seasons
            if int(s["team_count"]) > 1
        ]
        last_ts = last_seen.get(manager_key)
        records.append(
            sharp_score.ManagerRecord(
                user_id=manager_key,
                completed_seasons=len(seasons),
                observed_leagues=len(leagues),
                dynasty_leagues=len(leagues),
                completed_games=wins + losses + ties,
                wins=wins,
                losses=losses,
                ties=ties,
                playoff_appearances=sum(int(s["made_playoffs"]) for s in seasons),
                championships=sum(int(s["is_champion"]) for s in seasons),
                finish_percentiles=finishes,
                trades_completed=activity.get(manager_key, 0),
                days_since_last_activity=(
                    int((now_ms - last_ts) / 86_400_000) if last_ts else None
                ),
            )
        )
    return records, evidence


# ── seeded, messy ledgers ────────────────────────────────────────────

_SEASON_SQL = """
INSERT INTO manager_seasons
  (league_id, season, user_id, roster_id, wins, losses, ties,
   points_for, points_against, made_playoffs, is_champion, is_runner_up,
   finish_rank, team_count, is_complete, sharp_eligible, crawled_ms,
   platform, league_key, manager_key, source_identity_type,
   evidence_status, exclusion_reasons_json, metadata_json)
VALUES (?, ?, ?, '1', ?, ?, ?, 0, 0, ?, ?, 0, ?, ?, ?, ?, 0,
        ?, ?, ?, ?, NULL, ?, NULL)
"""

_MOVEMENT_SQL = """
INSERT INTO asset_movements
  (movement_id, tx_id, league_id, tx_type, asset_id, asset_type, action,
   user_id, ts, ingested_ms)
VALUES (?, ?, 'L0', ?, 'P1', 'player', 'add', ?, ?, 0)
"""

_STORED_REASONS = (None, "[]", '["custom_reason"]', "not json", '["", "  "]', '["x", "x"]')
_IDENTITIES = (
    IDENTITY_GLOBAL_VERIFIED,
    IDENTITY_GLOBAL_VERIFIED,
    "league_scoped_team",
    "name_only",
    "something_else",
    None,
)


def _maybe(rng: random.Random, value: Any, p_none: float) -> Any:
    return None if rng.random() < p_none else value


def _build_ledger(path, *, seed: int, managers: int, rows_per_manager: int, messy: bool):
    """A ledger whose rows exercise every branch of the builder.

    ``messy=False`` makes nearly every row eligible (the memory test wants
    the eligible-row path, which is what the retired builder retained).
    """
    rng = random.Random(seed)
    conn = platform_ledger.ensure_platform_schema(path)
    try:
        seasons = []
        movements = []
        managers_rows = []
        for m in range(managers):
            platform = "ffpc" if messy and m % 3 == 0 else "sleeper"
            user = f"u{m}"
            key = f"{platform}:{user}"
            if messy and m % 17 == 5:
                key = ""  # a row with no manager key is skipped
            if platform == "ffpc" and messy and m % 2 == 0:
                # The manager-level identity overrides the row's own.
                managers_rows.append(
                    (key, "ffpc", user, rng.choice(_IDENTITIES[:4]) or IDENTITY_GLOBAL_VERIFIED)
                )
            for r in range(rows_per_manager):
                team_count = rng.choice((12, 12, 10, 2, 1)) if messy else 12
                finish = rng.randint(1, max(1, team_count))
                league_id = f"L{rng.randint(0, 40)}"
                p_none = 0.04 if messy else 0.0
                seasons.append(
                    (
                        league_id,
                        str(2015 + r),
                        f"{user}-{r}" if not key else user,
                        _maybe(rng, rng.randint(0, 14), p_none),
                        _maybe(rng, rng.randint(0, 14), p_none),
                        _maybe(rng, rng.randint(0, 1), p_none),
                        _maybe(rng, rng.randint(0, 1), p_none),
                        _maybe(rng, rng.randint(0, 1), p_none),
                        _maybe(rng, finish, p_none),
                        _maybe(rng, team_count, p_none),
                        1 if not messy or rng.random() > 0.1 else 0,
                        1 if not messy or rng.random() > 0.1 else 0,
                        platform,
                        (None if messy and rng.random() < 0.1 else f"{platform}:{league_id}"),
                        key,
                        rng.choice(_IDENTITIES) if messy else IDENTITY_GLOBAL_VERIFIED,
                        rng.choice(_STORED_REASONS) if messy else None,
                    )
                )
            if key and (not messy or rng.random() < 0.7):
                for t in range(rng.randint(1, 4)):
                    movements.append(
                        (
                            f"mv-{m}-{t}",
                            f"tx-{m}-{t // 2}",
                            "trade" if rng.random() < 0.6 else "waiver",
                            user,
                            int(NOW_S * 1000) - rng.randint(0, 900) * DAY_MS,
                        )
                    )
        conn.executemany(_SEASON_SQL, seasons)
        # Legacy movement inserts take the Sleeper trigger path; FFPC
        # managers' movements are keyed explicitly below.
        conn.executemany(_MOVEMENT_SQL, movements)
        conn.execute(
            """
            UPDATE asset_movements
               SET manager_key = 'ffpc:' || user_id, platform = 'ffpc'
             WHERE CAST(SUBSTR(user_id, 2) AS INTEGER) % 3 = 0 AND ?
            """,
            (1 if messy else 0,),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO platform_managers
              (manager_key, platform, source_manager_id, source_identity_type)
            VALUES (?, ?, ?, ?)
            """,
            managers_rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW_S)


def _evidence_view(evidence):
    return [(key, status.to_dict()) for key, status in evidence.items()]


# ── parity ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
@pytest.mark.parametrize("min_season_rows", [1, 2, 4])
def test_streamed_builder_matches_the_retired_algorithm(
    tmp_path, frozen_clock, seed, min_season_rows
):
    path = tmp_path / "ledger.sqlite3"
    _build_ledger(path, seed=seed, managers=120, rows_per_manager=6, messy=True)

    expected_records, expected_evidence = _legacy_build_manager_records(
        ledger_path=path, min_season_rows=min_season_rows
    )
    records, evidence = platform_records.build_manager_records(
        ledger_path=path, min_season_rows=min_season_rows
    )

    # The fixture must actually reach every branch, or parity proves little.
    reasons = set().union(*(s.reasons for s in expected_evidence.values()))
    assert {
        "league_scoped_identity",
        "insufficient_multi_league_identity",
        "missing_completed_season",
        "unknown_or_ineligible_league_format",
        "missing_playoff_result",
        "missing_wins",
        "missing_team_count",
        "missing_recent_activity",
        "custom_reason",
    } <= reasons
    assert expected_records, "fixture produced no scoreable managers"
    if min_season_rows == 1:
        assert any(r.days_since_last_activity is None for r in expected_records)
        assert any(r.trades_completed for r in expected_records)
        assert any(len(r.finish_percentiles) < r.completed_seasons for r in expected_records)

    assert records == expected_records  # same records, same order
    assert _evidence_view(evidence) == _evidence_view(expected_evidence)


def test_empty_ledger(tmp_path, frozen_clock):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ensure_platform_schema(path).close()
    assert platform_records.build_manager_records(ledger_path=path) == ([], {})


# ── memory ───────────────────────────────────────────────────────────


def _traced_peak(fn) -> int:
    started = not tracemalloc.is_tracing()
    if started:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        before = tracemalloc.get_traced_memory()[0]
        fn()
        return tracemalloc.get_traced_memory()[1] - before
    finally:
        if started:
            tracemalloc.stop()


def _build_production_shaped_ledger(path, *, managers: int, seasons: int) -> int:
    """About production's shape: ~21 seasons per manager, every row eligible,
    a new league id each season (Sleeper re-keys leagues yearly), and 12
    managers sharing each league-season."""
    rng = random.Random(11)
    rows = []
    for m in range(managers):
        user = f"{1_000_000_000_000_000_000 + m}"
        for r in range(seasons):
            league = f"{900_000_000_000_000_000 + (m // 12) * seasons + r}"
            rows.append(
                (league, str(2005 + r), user, rng.randint(0, 14), rng.randint(0, 14), 0, 1, 0,
                 rng.randint(1, 12), 12, 1, 1, "sleeper", f"sleeper:{league}",
                 f"sleeper:{user}", IDENTITY_GLOBAL_VERIFIED, None)
            )  # fmt: skip
    conn = platform_ledger.ensure_platform_schema(path)
    try:
        conn.executemany(_SEASON_SQL, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def test_peak_per_row_is_a_fraction_of_the_retired_build(tmp_path, frozen_clock):
    path = tmp_path / "ledger.sqlite3"
    n_rows = _build_production_shaped_ledger(path, managers=1200, seasons=21)

    legacy = _traced_peak(lambda: _legacy_build_manager_records(ledger_path=path))
    streamed = _traced_peak(lambda: platform_records.build_manager_records(ledger_path=path))

    # Measured: about 940 B/row retired, about 100 B/row streamed.  A fresh
    # league-key string per row kept in a per-manager set (the first draft of
    # this fix) measured about 260 B/row and fails this bound.
    assert streamed * 6 < legacy, (streamed / n_rows, legacy / n_rows)


# ── single-flight in cohort_members ──────────────────────────────────


def test_concurrent_misses_share_one_computation(tmp_path, monkeypatch):
    cohort.reset_cohort_cache()
    calls = {"n": 0}
    entered = threading.Event()
    release = threading.Event()
    result = ([], {"marker": True})

    def _slow_compute(**kwargs):
        calls["n"] += 1
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(cohort, "_compute_cohort_members", _slow_compute)
    path = tmp_path / "ledger.sqlite3"  # absent file: a stable "-" fingerprint
    outputs: list[Any] = []

    def _call():
        outputs.append(cohort.cohort_members(qualification="all", ledger_path=path))

    first = threading.Thread(target=_call)
    first.start()
    assert entered.wait(10)
    others = [threading.Thread(target=_call) for _ in range(5)]
    for thread in others:
        thread.start()
    time.sleep(0.2)  # let the others miss the cache and queue on the compute
    release.set()
    for thread in (first, *others):
        thread.join(10)

    assert calls["n"] == 1
    assert len(outputs) == 6
    assert all(out is result for out in outputs)
    cohort.reset_cohort_cache()


def test_waiters_behind_a_failed_computation_share_its_error(tmp_path, monkeypatch):
    cohort.reset_cohort_cache()
    calls = {"n": 0}
    entered = threading.Event()
    release = threading.Event()

    def _failing_compute(**kwargs):
        calls["n"] += 1
        entered.set()
        assert release.wait(10)
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(cohort, "_compute_cohort_members", _failing_compute)
    path = tmp_path / "ledger.sqlite3"
    errors: list[BaseException] = []

    def _call():
        try:
            cohort.cohort_members(qualification="all", ledger_path=path)
        except RuntimeError as exc:
            errors.append(exc)

    first = threading.Thread(target=_call)
    first.start()
    assert entered.wait(10)
    others = [threading.Thread(target=_call) for _ in range(4)]
    for thread in others:
        thread.start()
    time.sleep(0.2)
    release.set()
    for thread in (first, *others):
        thread.join(10)

    # One computation failed; its waiters got that failure instead of each
    # recomputing (and failing) in turn.
    assert calls["n"] == 1
    assert len(errors) == 5
    cohort.reset_cohort_cache()


def test_a_failed_computation_does_not_wedge_the_next_caller(tmp_path, monkeypatch):
    cohort.reset_cohort_cache()
    calls = {"n": 0}

    def _flaky_compute(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger unavailable")
        return ([], {"ok": True})

    monkeypatch.setattr(cohort, "_compute_cohort_members", _flaky_compute)
    path = tmp_path / "ledger.sqlite3"
    with pytest.raises(RuntimeError):
        cohort.cohort_members(qualification="all", ledger_path=path)
    assert cohort.cohort_members(qualification="all", ledger_path=path) == ([], {"ok": True})
    assert calls["n"] == 2
    cohort.reset_cohort_cache()
