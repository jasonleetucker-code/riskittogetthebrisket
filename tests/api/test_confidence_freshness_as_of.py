"""D9 (2026-10-07 audit): the wall clock must not leak into stored confidence.

B11's freshness axis reads ``_source_freshness_flags`` →
``_build_source_timestamps``.  Those used ``datetime.now()`` and the repo root,
so the SAME snapshot rebuilt later (or from a replayed tree via ``csv_root``)
published different confidence — contradicting "the same snapshot must
produce the same board" that ``_payload_as_of`` already enforces for content
freshness.  The board's own as-of and its ``csv_root`` now drive both the
flags and the published ``dataFreshness.sourceTimestamps`` block (which must
agree, so confidence and the freshness panel cannot disagree).

A board with no as-of has no "fetch age at T": every flag is UNKNOWN (``None``),
never fresh, mirroring ``_load_source_weighting``'s fail-closed posture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api import data_contract as dc

KEY = "dlfSf"
AS_OF = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _tree(root: Path, *, fetched_at: datetime) -> Path:
    """A minimal replay tree: the dlfSf CSV plus its fetch-success stamp."""
    cfg = dc._SOURCE_CSV_PATHS[KEY]
    rel = cfg if isinstance(cfg, str) else cfg["path"]
    csv = root / rel
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text("name,rank\nA,1\n", encoding="utf-8")
    state = root / "data" / "scrape_state"
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{KEY}_last_success").write_text(str(fetched_at.timestamp()), encoding="utf-8")
    return root


def test_fetch_age_is_measured_at_the_boards_as_of_not_the_wall_clock(tmp_path):
    budget = dc._SOURCE_MAX_AGE_HOURS[KEY]
    root = _tree(tmp_path, fetched_at=AS_OF - timedelta(hours=1))
    entry = dc._build_source_timestamps(as_of=AS_OF, csv_root=root)[KEY]
    # One hour old AT THE BOARD'S TIME — fresh, whatever today's date is
    # (the wall clock is more than a month later, which would read stale).
    assert entry["ageHours"] == pytest.approx(1.0)
    assert 1.0 < budget
    assert entry["staleness"] == "fresh"
    assert dc._source_freshness_flags(AS_OF, root)[KEY] is True


def test_the_same_snapshot_gives_the_same_flags_whenever_it_is_rebuilt(tmp_path, monkeypatch):
    root = _tree(tmp_path, fetched_at=AS_OF - timedelta(hours=1))
    first = dc._source_freshness_flags(AS_OF, root)

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 - a frozen "much later" clock
            return datetime(2027, 1, 1, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(dc, "datetime", _Later)
    assert dc._source_freshness_flags(AS_OF, root) == first


def test_stale_at_the_boards_time_is_stale(tmp_path):
    budget = dc._SOURCE_MAX_AGE_HOURS[KEY]
    root = _tree(tmp_path, fetched_at=AS_OF - timedelta(hours=budget + 5))
    assert dc._build_source_timestamps(as_of=AS_OF, csv_root=root)[KEY]["staleness"] == "stale"
    assert dc._source_freshness_flags(AS_OF, root)[KEY] is False


def test_csv_root_is_honoured_for_the_csv_and_the_stamp(tmp_path):
    """A replay tree with no dlfSf CSV is ``missing`` there, whatever the repo
    root holds."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert dc._build_source_timestamps(as_of=AS_OF, csv_root=empty)[KEY]["staleness"] == "missing"
    assert dc._source_freshness_flags(AS_OF, empty)[KEY] is None


def test_a_fetch_after_the_boards_as_of_is_not_a_negative_age(tmp_path):
    root = _tree(tmp_path, fetched_at=AS_OF + timedelta(hours=3))
    entry = dc._build_source_timestamps(as_of=AS_OF, csv_root=root)[KEY]
    assert entry["ageHours"] == 0.0
    assert entry["staleness"] == "fresh"


def test_no_as_of_is_unknown_never_fresh(tmp_path):
    root = _tree(tmp_path, fetched_at=AS_OF)
    entry = dc._build_source_timestamps(as_of=None, csv_root=root)[KEY]
    assert entry["staleness"] == "unknown"
    assert entry["ageHours"] is None
    assert dc._source_freshness_flags(None, root)[KEY] is None
