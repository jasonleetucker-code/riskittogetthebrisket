"""The contract's freshness budget must not be STRICTER than the alert owner's.

The sibling ``test_freshness_budget_not_laxer_than_alerts.py`` pins one
direction (the board must never count evidence as current after the operator
has been told it is stale).  This pins the other.

WHY (owner decision 2026-11-17, intake TC3-3)
──────────────────────────────────────────────
Fifteen sources carried a 6-hour budget, derived for 2-hourly CI fetchers,
while the alert engine gave them 24 hours.  Their fetch stamps advance only
when ``scheduled-refresh.yml`` lands, which GitHub starts about 3.6 times a
day (``docs/ops/SCRAPE_CADENCE_MEASUREMENT_2026-11-09.md``; gaps of 8-12 hours
on 2026-11-17).  So every board built more than 6 hours after the last refresh
read nearly every source as stale, with no alert raised: rebuilt at
production's 20:01 UTC board time on 2026-11-17, 190 of the top 200 players
were ``freshness: low``.  /trade then withheld every asset and the War Room
answered "not enough evidence" for every team of the owner's 3-team trade.

A board stricter than the alert engine is the mirror of audit finding F-6: the
operator sees healthy sources while every decision surface refuses to use
them.  Both owners answer the same question ("how stale may this FETCH be"),
so with the sibling test the two numbers are equal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api.source_health_alerts import load_thresholds, resolve_threshold

#: The sources whose budget the 2026-11-17 decision moved from 6 to 24 hours.
OWNER_DECISION_2026_11_17_KEYS = (
    "ktc",
    "ktcSfTep",
    "ktcCrowdSfTep",
    "ktcTradesSfTep",
    "ktcCrowdTradesSfTep",
    "idpTradeCalc",
    "dynastyNerdsSfTep",
    "fantasyProsIdp",
    "dynastyDaddySf",
    "fantasyCalc",
    "otcffbSf",
    "draftSharks",
    "draftSharksIdp",
    "fantasyNavigatorSf",
    "pfkDynasty",
)

AS_OF = datetime(2026, 11, 17, 20, 1, 59, tzinfo=timezone.utc)


def _alert_threshold(key: str) -> float:
    return float(resolve_threshold(key, load_thresholds()))


@pytest.mark.parametrize("key", sorted(dc._SOURCE_MAX_AGE_HOURS))
def test_contract_budget_is_not_stricter_than_the_alert_threshold(key: str) -> None:
    budget = float(dc._SOURCE_MAX_AGE_HOURS[key])
    threshold = _alert_threshold(key)
    assert budget >= threshold, (
        f"{key}: the board calls this source stale after {budget}h while the alert "
        f"engine still calls it healthy until {threshold}h — every decision surface "
        f"withholds evidence the operator is told is fine"
    )


def test_the_decision_keys_are_all_budgeted() -> None:
    """Guards the replay below against silently testing a renamed key."""
    missing = [k for k in OWNER_DECISION_2026_11_17_KEYS if k not in dc._SOURCE_MAX_AGE_HOURS]
    assert missing == []


def _replay_tree(root: Path, *, fetched_at: datetime) -> Path:
    """Every decision key's CSV plus a fetch-success stamp at ``fetched_at``."""
    state = root / "data" / "scrape_state"
    state.mkdir(parents=True, exist_ok=True)
    for key in OWNER_DECISION_2026_11_17_KEYS:
        cfg = dc._SOURCE_CSV_PATHS[key]
        rel = cfg if isinstance(cfg, str) else cfg["path"]
        csv = root / rel
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.write_text("name,rank\nA,1\n", encoding="utf-8")
        (state / f"{key}_last_success").write_text(str(fetched_at.timestamp()), encoding="utf-8")
    return root


@pytest.mark.parametrize("hours_since_refresh", [6.1, 6.4, 12.0, 23.5])
def test_a_board_built_between_refreshes_still_reads_them_as_fresh(
    tmp_path: Path, hours_since_refresh: float
) -> None:
    """The 2026-11-17 incident: stamps from the 13:55 refresh, board at 20:01."""
    root = _replay_tree(tmp_path, fetched_at=AS_OF - timedelta(hours=hours_since_refresh))
    flags = dc._source_freshness_flags(AS_OF, root)
    stale = [k for k in OWNER_DECISION_2026_11_17_KEYS if flags.get(k) is not True]
    assert stale == [], f"read as not fresh {hours_since_refresh}h after a refresh: {stale}"


def test_a_source_a_full_day_old_is_still_stale(tmp_path: Path) -> None:
    """The budget still bites: a day-old fetch is stale, as the alert engine says."""
    root = _replay_tree(tmp_path, fetched_at=AS_OF - timedelta(hours=24.5))
    flags = dc._source_freshness_flags(AS_OF, root)
    not_stale = [k for k in OWNER_DECISION_2026_11_17_KEYS if flags.get(k) is not False]
    assert not_stale == [], f"a 24.5h-old fetch read as not stale: {not_stale}"
