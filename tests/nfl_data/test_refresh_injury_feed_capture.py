"""``scripts/refresh_injury_feed.py``: as-known capture, the fetch proof, and SHADOW-ONLY events.

* A PROVEN fetch is appended to the injury history.
* An UNPROVEN fetch (ESPN failed, ``fetch_injuries`` returned ``[]``) changes
  nothing: no ACTIVATED_RETURN storm, no history row claiming a healthy league,
  and the prior snapshot is not overwritten with ``[]``.  Before this, a single
  failed fetch emitted a "recovered" event for every injured player and wiped
  the prior, so the next good fetch re-emitted every injury as new.
* A fetch whose rows the parser cannot read (the 2026-10 id change) is a FAILED
  fetch, logged with the feed's own reason -- never "a fetch with zero injuries".
* First non-empty run with an empty prior SEEDS the prior silently (otherwise the
  ~274 currently-injured players would read as new transitions).
* Derived events go to the SHADOW ledger, never to ``data/bdvm/events/<season>.json``
  (``src/bdvm/service.py`` loads that for every BDVM valuation) -- the same rule
  #1926 applied to depth charts.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import logging
import sys
from pathlib import Path

import pytest

from src.api import feature_flags
from src.nfl_data import cache as nfl_cache
from src.nfl_data import injury_feed, injury_history
from src.nfl_data.injury_feed import CACHE_KEY, InjuryEntry
from src.utils import append_ledger as al

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "refresh_injury_feed.py"
_CURRENT_FIXTURE = Path(__file__).parent / "fixtures" / "espn_injuries_2026-10-26.json"

#: Sleeper ids are 1000 + the ESPN id's last digit for the test players; two
#: resolve by exact ESPN id, the rest by exact name (Sleeper's espn_id is sparse).
DIRECTORY = {
    "100": {
        "full_name": "Alpha Player",
        "position": "WR",
        "team": "BUF",
        "active": True,
        "espn_id": "1",
    },
    "200": {
        "full_name": "Beta Player",
        "position": "WR",
        "team": "BUF",
        "active": True,
        "espn_id": "2",
    },
}
#: The players of the real-shape fixture, none of them with an ESPN id on file.
FIXTURE_DIRECTORY = {
    "1001": {
        "full_name": "Max Melton",
        "position": "DB",
        "team": "ARI",
        "active": True,
        "espn_id": "4698113",
    },
    "1002": {"full_name": "Jeremiyah Love", "position": "RB", "team": "ARI", "active": True},
    "1003": {"full_name": "Jack Strand", "position": "QB", "team": "ATL", "active": True},
    "1004": {"full_name": "Michael Jerrell", "position": "OL", "team": "ATL", "active": True},
    "1005": {"full_name": "Olaivavega Ioane", "position": "OL", "team": "BAL", "active": True},
    "1006": {"full_name": "Taylor Moton", "position": "OL", "team": "CAR", "active": True},
    "1007": {"full_name": "Anthony Johnson", "position": "DB", "team": "CHI", "active": True},
    "1008": {"full_name": "Jonathan Greenard", "position": "LB", "team": "PHI", "active": True},
}


def _load_script():
    spec = importlib.util.spec_from_file_location("refresh_injury_feed_under_test", _SCRIPT)
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
    shadow = tmp_path / "injury_events_shadow.json"
    monkeypatch.setattr(mod, "_PRIOR_PATH", prior)
    monkeypatch.setattr(mod, "_SHADOW_PATH", shadow)
    # The per-player return-evidence pass is an independent network step with
    # its own tests (tests/nfl_data/test_injury_return_evidence.py).
    monkeypatch.setattr(mod, "_refresh_return_evidence", lambda: None)
    history = tmp_path / "history"
    monkeypatch.setenv("RISKIT_INJURY_HISTORY_DIR", str(history))
    directory = {"value": (DIRECTORY, {"path": "fixture"})}
    monkeypatch.setattr(injury_history, "load_directory", lambda *a, **k: directory["value"])
    # TRIPWIRE: nothing may ever be merged into the BDVM events file.
    merged: list = []

    def _merge(events, **_kw):
        merged.extend(events)
        return {"ok": True}

    import src.bdvm.news_events as news_events

    monkeypatch.setattr(news_events, "merge_events_file", _merge)
    bdvm_events_dir = tmp_path / "bdvm_events"
    import src.bdvm.events as bdvm_events

    monkeypatch.setattr(bdvm_events, "EVENTS_DIR", bdvm_events_dir)
    yield {
        "mod": mod,
        "cache_dir": cache_dir,
        "prior": prior,
        "shadow": shadow,
        "history": history,
        "merged": merged,
        "bdvm_events_dir": bdvm_events_dir,
        "directory": directory,
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


def _shadow_runs(env) -> list[dict]:
    if not env["shadow"].exists():
        return []
    doc = json.loads(env["shadow"].read_text(encoding="utf-8"))
    assert doc["status"] == "shadow_not_loaded"
    return doc["runs"]


def _assert_nothing_reached_bdvm(env):
    assert env["merged"] == []
    assert not env["bdvm_events_dir"].exists()


def test_failed_fetch_changes_nothing(env):
    injured = [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "IR")]
    env["prior"].write_text(json.dumps([e.to_dict() for e in injured]), encoding="utf-8")
    before = env["prior"].read_text(encoding="utf-8")
    _fetch_fails(env)

    rc = env["mod"].main([])

    assert rc == 1
    # No "everyone recovered" events from a fetch that did not happen.
    _assert_nothing_reached_bdvm(env)
    assert _shadow_runs(env) == []
    assert env["prior"].read_text(encoding="utf-8") == before
    assert list(al.iter_all_records(env["history"])) == []


def test_proven_fetch_is_captured_and_derives_a_shadow_event_never_a_bdvm_event(env):
    env["prior"].write_text(
        json.dumps([_entry("1", "Alpha Player", "QUESTIONABLE").to_dict()]), encoding="utf-8"
    )
    _fetch_writes_cache(env, [_entry("1", "Alpha Player", "OUT")])

    rc = env["mod"].main([])

    assert rc == 0
    _assert_nothing_reached_bdvm(env)
    [run] = _shadow_runs(env)
    assert run["mode"] == "derived"
    assert [e["eventType"] for e in run["events"]] == ["INJURY"]
    assert run["events"][0]["confidence"] == 0.85  # the events are what WOULD have merged
    assert run["transitions"] == {"injury_worsened": 1}
    [prov] = run["eventProvenance"]
    assert prov["eventId"] == run["events"][0]["eventId"]
    assert (prov["espnAthleteId"], prov["sleeperId"]) == ("1", "100")
    assert (prov["priorStatus"], prov["newStatus"]) == ("QUESTIONABLE", "OUT")
    [rec] = list(al.iter_all_records(env["history"]))
    assert rec["kind"] == "snapshot"
    assert rec["entries"][0]["status"] == "OUT"
    saved = json.loads(env["prior"].read_text(encoding="utf-8"))
    assert saved[0]["status"] == "OUT" and saved[0]["sleeperId"] == "100"


def test_proven_empty_report_is_real_and_recorded_and_recovers_in_shadow_only(env):
    env["prior"].write_text(
        json.dumps([_entry("1", "Alpha Player", "OUT").to_dict()]), encoding="utf-8"
    )
    _fetch_writes_cache(env, [])

    rc = env["mod"].main([])

    assert rc == 0
    _assert_nothing_reached_bdvm(env)
    [run] = _shadow_runs(env)
    assert [e["eventType"] for e in run["events"]] == ["ACTIVATED_RETURN"]
    [rec] = list(al.iter_all_records(env["history"]))
    assert rec["entryCount"] == 0


def test_archive_failure_does_not_fail_the_refresh(env):
    blocker = env["prior"].parent / "blocker"
    blocker.write_text("x")
    env["monkeypatch"].setenv("RISKIT_INJURY_HISTORY_DIR", str(blocker / "sub"))
    _fetch_writes_cache(env, [_entry("1", "Alpha Player", "OUT")])

    assert env["mod"].main([]) == 0


# ── first run: seed the prior silently ───────────────────────────────────────


@pytest.mark.parametrize("prior_text", [None, "[]", "not json", '{"a": 1}'])
def test_first_non_empty_run_with_no_usable_prior_seeds_silently(env, prior_text):
    """The box's state was ``[]``: the parser had never produced an entry."""
    if prior_text is not None:
        env["prior"].write_text(prior_text, encoding="utf-8")
    _fetch_writes_cache(env, [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "IR")])

    assert env["mod"].main([]) == 0

    _assert_nothing_reached_bdvm(env)
    [run] = _shadow_runs(env)
    assert run["mode"] == "seeded"
    assert run["events"] == [] and run["transitions"] == {} and run["recoveries"] == 0
    assert "eventProvenance" not in run
    saved = json.loads(env["prior"].read_text(encoding="utf-8"))
    assert {(d["espnAthleteId"], d["sleeperId"]) for d in saved} == {("1", "100"), ("2", "200")}
    [rec] = list(al.iter_all_records(env["history"]))  # history is recorded in full
    assert rec["entryCount"] == 2


def test_second_run_after_seeding_derives_a_transition_into_shadow_only(env):
    _fetch_writes_cache(env, [_entry("1", "Alpha Player", "QUESTIONABLE")])
    assert env["mod"].main([]) == 0  # seeds
    nfl_cache.evict(CACHE_KEY, cache_dir=env["cache_dir"])

    _fetch_writes_cache(
        env, [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "QUESTIONABLE")]
    )
    assert env["mod"].main([]) == 0

    _assert_nothing_reached_bdvm(env)
    first, second = _shadow_runs(env)
    assert (first["mode"], first["events"]) == ("seeded", [])
    assert second["mode"] == "derived"
    assert second["transitions"] == {"healthy_to_injured": 1, "injury_worsened": 1}
    assert sorted(e["eventType"] for e in second["events"]) == ["INJURY", "INJURY"]


def test_a_player_still_listed_but_unresolved_is_neither_recovered_nor_forgotten(env):
    _fetch_writes_cache(
        env, [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "OUT")]
    )
    assert env["mod"].main([]) == 0  # seeds both
    nfl_cache.evict(CACHE_KEY, cache_dir=env["cache_dir"])

    # Alpha leaves the directory (a refresh gap): still on the report, unresolvable now.
    env["directory"]["value"] = ({"200": DIRECTORY["200"]}, {"path": "fixture"})
    _fetch_writes_cache(
        env, [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "OUT")]
    )
    assert env["mod"].main([]) == 0

    second = _shadow_runs(env)[-1]
    assert second["events"] == [] and second["recoveries"] == 0
    assert second["identity"]["unresolvedByReason"] == {"no_candidate": 1}
    saved = json.loads(env["prior"].read_text(encoding="utf-8"))
    assert {d["espnAthleteId"] for d in saved} == {"1", "2"}  # Alpha's last row is carried


# ── identity alarm ───────────────────────────────────────────────────────────


def test_unusable_identity_fails_the_run_but_history_is_kept(env):
    injured = [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "IR")]
    env["prior"].write_text(json.dumps([e.to_dict() for e in injured]), encoding="utf-8")
    before = env["prior"].read_text(encoding="utf-8")
    env["directory"]["value"] = (
        None,
        {"path": None, "nullReason": "no_readable_sleeper_directory"},
    )
    _fetch_writes_cache(env, injured)

    assert env["mod"].main([]) == 1

    _assert_nothing_reached_bdvm(env)
    assert _shadow_runs(env) == []
    assert env["prior"].read_text(encoding="utf-8") == before
    [rec] = list(al.iter_all_records(env["history"]))  # the real parsed entries are evidence
    assert rec["entryCount"] == 2 and rec["unresolvedCount"] == 2


# ── the real-shape payload through the REAL fetch_injuries ───────────────────


def _real_fetch_with_body(env, body: bytes):
    from src.utils import circuit_breaker

    circuit_breaker.reset_all_for_tests()
    nfl_cache.evict(CACHE_KEY, cache_dir=env["cache_dir"])
    env["monkeypatch"].setattr(
        env["mod"],
        "fetch_injuries",
        lambda: injury_feed.fetch_injuries(_url_opener=lambda req, timeout=None: io.BytesIO(body)),
    )


def test_shape_drift_is_a_failed_fetch_and_changes_nothing(env):
    injured = [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "IR")]
    env["prior"].write_text(json.dumps([e.to_dict() for e in injured]), encoding="utf-8")
    before = env["prior"].read_text(encoding="utf-8")
    _real_fetch_with_body(env, b'{"teams": "renamed upstream"}')

    assert env["mod"].main([]) == 1
    _assert_nothing_reached_bdvm(env)
    assert env["prior"].read_text(encoding="utf-8") == before
    assert list(al.iter_all_records(env["history"])) == []


def test_genuine_empty_report_through_real_fetch_is_recorded(env):
    env["prior"].write_text(
        json.dumps([_entry("1", "Alpha Player", "OUT").to_dict()]), encoding="utf-8"
    )
    _real_fetch_with_body(env, b'{"injuries": []}')

    assert env["mod"].main([]) == 0
    _assert_nothing_reached_bdvm(env)
    assert [e["eventType"] for e in _shadow_runs(env)[0]["events"]] == ["ACTIVATED_RETURN"]
    [rec] = list(al.iter_all_records(env["history"]))
    assert rec["entryCount"] == 0


def test_raw_rows_but_zero_parsed_is_a_failed_fetch_never_a_proven_empty_one(env, caplog):
    """The 2026-10 incident: a body full of rows, an id the parser cannot find."""
    injured = [_entry("1", "Alpha Player", "OUT"), _entry("2", "Beta Player", "IR")]
    env["prior"].write_text(json.dumps([e.to_dict() for e in injured]), encoding="utf-8")
    before = env["prior"].read_text(encoding="utf-8")
    payload = json.loads(_CURRENT_FIXTURE.read_text(encoding="utf-8"))
    for block in payload["injuries"]:
        for row in block["injuries"]:
            row["athlete"]["links"] = []
    _real_fetch_with_body(env, json.dumps(payload).encode("utf-8"))

    with caplog.at_level(logging.INFO):
        rc = env["mod"].main([])

    assert rc == 1
    messages = [r.getMessage() for r in caplog.records]
    assert not any("fetch proven" in m for m in messages)
    assert any("no_injury_entries_parsed:raw=10" in m for m in messages)  # the feed's own reason
    _assert_nothing_reached_bdvm(env)
    assert _shadow_runs(env) == []
    assert env["prior"].read_text(encoding="utf-8") == before
    assert list(al.iter_all_records(env["history"])) == []


def test_current_shape_end_to_end_seeds_then_derives_shadow_events_only(env):
    env["directory"]["value"] = (FIXTURE_DIRECTORY, {"path": "fixture"})
    body = _CURRENT_FIXTURE.read_bytes()
    _real_fetch_with_body(env, body)

    assert env["mod"].main([]) == 0

    # First run: 8 real entries parsed, prior seeded, NO events, history in full.
    [run] = _shadow_runs(env)
    assert run["mode"] == "seeded" and run["events"] == []
    assert run["parse"]["parsed"] == 8 and run["parse"]["rawEntries"] == 10
    assert run["parse"]["skipped"] == {"status_active": 1, "status_untracked:SUSPENSION": 1}
    assert run["identity"]["resolved"] == 8
    assert run["identity"]["byMethod"] == {"espn_id": 1, "name:exact_clean": 7}
    seeded = json.loads(env["prior"].read_text(encoding="utf-8"))
    assert len(seeded) == 8 and all(d["sleeperId"] for d in seeded)
    [rec] = list(al.iter_all_records(env["history"]))
    assert rec["entryCount"] == 8
    melton = next(e for e in rec["entries"] if e["espnAthleteId"] == "4698113")
    assert (melton["status"], melton["injuryType"], melton["source"]) == (
        "OUT",
        "Knee",
        "basic/manual",
    )
    assert melton["identity"]["status"] == "resolved"

    # Later run: Moton worsens (Doubtful -> Out), Melton leaves the report.
    payload = json.loads(body)
    for block in payload["injuries"]:
        block["injuries"] = [
            r for r in block["injuries"] if r["athlete"]["displayName"] != "Max Melton"
        ]
        for row in block["injuries"]:
            if row["athlete"]["displayName"] == "Taylor Moton":
                row["status"] = "Out"
    _real_fetch_with_body(env, json.dumps(payload).encode("utf-8"))

    assert env["mod"].main([]) == 0

    _assert_nothing_reached_bdvm(env)
    second = _shadow_runs(env)[-1]
    assert second["mode"] == "derived"
    assert second["transitions"] == {"injury_worsened": 1}
    assert second["recoveries"] == 1
    assert sorted(e["eventType"] for e in second["events"]) == ["ACTIVATED_RETURN", "INJURY"]
    assert {p["sleeperId"] for p in second["eventProvenance"]} == {"1001", "1006"}


# ── structural guard: no code path writes injury events to the BDVM events file ──


def test_script_has_no_code_path_to_the_bdvm_events_file():
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))
    assert "merge_events_file" not in imported | called
    assert "EVENTS_DIR" not in imported
    assert not any(m.startswith("src.bdvm") for m in imported)
