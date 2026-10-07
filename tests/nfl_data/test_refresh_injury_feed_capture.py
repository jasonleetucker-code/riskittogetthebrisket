"""``scripts/refresh_injury_feed.py``: as-known capture + the fetch proof.

* A PROVEN fetch is appended to the injury history (and still drives events).
* An UNPROVEN fetch (ESPN failed, ``fetch_injuries`` returned ``[]``) changes
  nothing: no ACTIVATED_RETURN storm, no history row claiming a healthy league,
  and the prior snapshot is not overwritten with ``[]``.  Before this, a single
  failed fetch emitted a "recovered" event for every injured player and wiped
  the prior, so the next good fetch re-emitted every injury as new.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.api import feature_flags
from src.nfl_data import cache as nfl_cache
from src.nfl_data.injury_feed import CACHE_KEY, InjuryEntry
from src.utils import append_ledger as al

REPO = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "refresh_injury_feed_under_test", REPO / "scripts" / "refresh_injury_feed.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _entry(eid, name, status):
    return InjuryEntry(
        espn_athlete_id=eid,
        full_name=name,
        position="WR",
        team_abbrev="BUF",
        status=status,
        body_part="Knee",
        description="",
        date_reported="",
        returning="",
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    mod = _load_script()
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(nfl_cache, "_default_cache_dir", lambda: cache_dir)
    prior = tmp_path / "injuries_prior.json"
    monkeypatch.setattr(mod, "_PRIOR_PATH", prior)
    history = tmp_path / "history"
    monkeypatch.setenv("RISKIT_INJURY_HISTORY_DIR", str(history))
    merged: list = []

    def _merge(events, **_kw):
        merged.extend(events)
        return {"ok": True}

    import src.bdvm.news_events as news_events

    monkeypatch.setattr(news_events, "merge_events_file", _merge)
    yield {
        "mod": mod,
        "cache_dir": cache_dir,
        "prior": prior,
        "history": history,
        "merged": merged,
        "monkeypatch": monkeypatch,
    }
    feature_flags.reload()


def _fetch_writes_cache(env, entries):
    def _fetch():
        nfl_cache.put(CACHE_KEY, [e.to_dict() for e in entries], cache_dir=env["cache_dir"])
        return list(entries)

    env["monkeypatch"].setattr(env["mod"], "fetch_injuries", _fetch)


def _fetch_fails(env):
    env["monkeypatch"].setattr(env["mod"], "fetch_injuries", lambda: [])


def test_failed_fetch_changes_nothing(env):
    injured = [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "IR")]
    env["prior"].write_text(json.dumps([e.to_dict() for e in injured]), encoding="utf-8")
    before = env["prior"].read_text(encoding="utf-8")
    _fetch_fails(env)

    rc = env["mod"].main([])

    assert rc == 1
    # No "everyone recovered" events from a fetch that did not happen.
    assert env["merged"] == []
    assert env["prior"].read_text(encoding="utf-8") == before
    assert list(al.iter_all_records(env["history"])) == []


def test_proven_fetch_is_captured_and_still_drives_events(env):
    env["prior"].write_text(
        json.dumps([_entry("1", "Alpha Player", "QUESTIONABLE").to_dict()]), encoding="utf-8"
    )
    _fetch_writes_cache(env, [_entry("1", "Alpha Player", "OUT")])

    rc = env["mod"].main([])

    assert rc == 0
    assert [e["eventType"] for e in env["merged"]] == ["INJURY"]
    [rec] = list(al.iter_all_records(env["history"]))
    assert rec["kind"] == "snapshot"
    assert rec["entries"][0]["status"] == "OUT"
    assert json.loads(env["prior"].read_text(encoding="utf-8"))[0]["status"] == "OUT"


def test_proven_empty_report_is_real_and_recorded(env):
    env["prior"].write_text(
        json.dumps([_entry("1", "Alpha Player", "OUT").to_dict()]), encoding="utf-8"
    )
    _fetch_writes_cache(env, [])

    rc = env["mod"].main([])

    assert rc == 0
    assert [e["eventType"] for e in env["merged"]] == ["ACTIVATED_RETURN"]
    [rec] = list(al.iter_all_records(env["history"]))
    assert rec["entryCount"] == 0


def test_archive_failure_does_not_fail_the_refresh(env):
    blocker = env["prior"].parent / "blocker"
    blocker.write_text("x")
    env["monkeypatch"].setenv("RISKIT_INJURY_HISTORY_DIR", str(blocker / "sub"))
    _fetch_writes_cache(env, [_entry("1", "Alpha Player", "OUT")])

    assert env["mod"].main([]) == 0
