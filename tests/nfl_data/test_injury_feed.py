"""Tests for the ESPN injury feed parser + signal diff."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest

from src.api import feature_flags
from src.nfl_data import injury_feed

#: A trimmed REAL response (2026-10-26): comments truncated, links reduced to the
#: player card / stats / app links, logos and notes removed.  Ten rows over seven
#: team blocks: six injury statuses plus a news-only ``Active`` row, a
#: ``Suspension``, negative report ids, partial ``details`` and a row with no
#: headshot.
_CURRENT_FIXTURE = Path(__file__).parent / "fixtures" / "espn_injuries_2026-10-26.json"


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _sample_payload():
    """Mimics ESPN's /injuries response shape."""
    return {
        "injuries": [
            {
                "team": {"abbreviation": "BUF"},
                "injuries": [
                    {
                        "athlete": {
                            "id": "3918298",
                            "displayName": "Josh Allen",
                            "position": {"abbreviation": "QB"},
                        },
                        "status": "Questionable",
                        "details": {
                            "type": "Knee",
                            "location": "Knee",
                            "returnDate": "2026-11-15",
                        },
                        "date": "2026-11-10T00:00:00Z",
                        "shortComment": "Limited in practice",
                    },
                    {
                        "athlete": {
                            "id": "4242",
                            "displayName": "Healthy Guy",
                            "position": {"abbreviation": "RB"},
                        },
                        "status": "Probable",  # not in ACTIVE_STATUSES after normalize? Let's check.
                        "details": {"type": "Ankle"},
                        "date": "2026-11-10T00:00:00Z",
                    },
                ],
            },
            {
                "team": {"abbreviation": "SF"},
                "injuries": [
                    {
                        "athlete": {
                            "id": "5555",
                            "displayName": "Out Guy",
                            "position": {"abbreviation": "WR"},
                        },
                        "status": "Out",
                        "details": {"type": "Hamstring", "returnDate": "Unknown"},
                        "date": "2026-11-09T00:00:00Z",
                    }
                ],
            },
        ]
    }


def test_flag_off_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "0")
    feature_flags.reload()
    # No network call: opener should never be invoked.
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        return io.BytesIO(b"{}")

    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert out == []
    assert calls == []


def test_flag_on_parses_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        return io.BytesIO(json.dumps(_sample_payload()).encode("utf-8"))

    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    names = {e.full_name for e in out}
    # Questionable + Out = both active; Probable (→ DAY_TO_DAY) is active too.
    assert "Josh Allen" in names
    assert "Out Guy" in names
    # Second call — cache hit, opener not invoked again.
    out2 = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert len(calls) == 1
    assert len(out2) == len(out)


def test_status_normalization():
    assert injury_feed._normalize_status("Out") == "OUT"  # noqa: SLF001
    assert injury_feed._normalize_status("Injured Reserve") == "IR"  # noqa: SLF001
    assert injury_feed._normalize_status("Questionable") == "QUESTIONABLE"  # noqa: SLF001
    assert injury_feed._normalize_status("Day-to-Day") == "DAY_TO_DAY"  # noqa: SLF001


def test_malformed_payload_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()

    def opener(req, timeout=None):
        return io.BytesIO(b'{"not": "expected shape"}')

    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert out == []


def test_network_error_returns_empty_not_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()

    def opener(req, timeout=None):
        raise TimeoutError("upstream")

    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert out == []


def test_diff_new_injury_fires():
    prior = []
    current = [
        injury_feed.InjuryEntry(
            espn_athlete_id="X",
            full_name="X Y",
            position="WR",
            team_abbrev="SF",
            status="OUT",
            body_part="Knee",
            description="",
            date_reported="",
            returning="",
        )
    ]
    signals = injury_feed.diff_for_signals(prior, current)
    assert len(signals) == 1
    assert signals[0]["transition"] == "healthy_to_injured"


def test_diff_worsened_fires():
    prior = [
        injury_feed.InjuryEntry(
            espn_athlete_id="X",
            full_name="X Y",
            position="WR",
            team_abbrev="SF",
            status="QUESTIONABLE",
            body_part="",
            description="",
            date_reported="",
            returning="",
        )
    ]
    current = [
        injury_feed.InjuryEntry(
            espn_athlete_id="X",
            full_name="X Y",
            position="WR",
            team_abbrev="SF",
            status="OUT",
            body_part="",
            description="",
            date_reported="",
            returning="",
        )
    ]
    signals = injury_feed.diff_for_signals(prior, current)
    assert len(signals) == 1
    assert signals[0]["transition"] == "injury_worsened"


def test_diff_unchanged_does_not_fire():
    e = injury_feed.InjuryEntry(
        espn_athlete_id="X",
        full_name="X Y",
        position="WR",
        team_abbrev="SF",
        status="OUT",
        body_part="",
        description="",
        date_reported="",
        returning="",
    )
    signals = injury_feed.diff_for_signals([e], [e])
    assert signals == []


def test_diff_recovered_does_not_fire_sell_signal():
    """A player who GETS BETTER → we DON'T emit a SELL transition.
    Recovery is a different signal class covered elsewhere."""
    prior = [
        injury_feed.InjuryEntry(
            espn_athlete_id="X",
            full_name="X Y",
            position="WR",
            team_abbrev="SF",
            status="OUT",
            body_part="",
            description="",
            date_reported="",
            returning="",
        )
    ]
    current: list[injury_feed.InjuryEntry] = []
    signals = injury_feed.diff_for_signals(prior, current)
    assert signals == []


# ── shape drift is a FAILED fetch, not an empty report (G4 review) ─────────


@pytest.fixture
def _fresh_breaker():
    from src.utils import circuit_breaker

    circuit_breaker.reset_all_for_tests()
    yield
    circuit_breaker.reset_all_for_tests()


@pytest.mark.parametrize(
    "body",
    [
        b'{"not": "expected shape"}',
        b'{"injuries": {"oops": 1}}',
        b"[1, 2, 3]",
        b'{"injuries": [{"team": {"abbreviation": "BUF"}, "athletes": []}]}',
    ],
)
def test_shape_drift_is_not_cached(monkeypatch, tmp_path, body, _fresh_breaker):
    from src.nfl_data import cache as nfl_cache

    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    out = injury_feed.fetch_injuries(
        _url_opener=lambda req, timeout=None: io.BytesIO(body), cache_dir=tmp_path
    )
    assert out == []
    # Nothing cached: a caller checking the cache sees a failed fetch.
    assert nfl_cache.entry_fetched_at(injury_feed.CACHE_KEY, cache_dir=tmp_path) is None


def test_genuine_empty_report_is_cached(monkeypatch, tmp_path, _fresh_breaker):
    from src.nfl_data import cache as nfl_cache

    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    out = injury_feed.fetch_injuries(
        _url_opener=lambda req, timeout=None: io.BytesIO(b'{"injuries": []}'),
        cache_dir=tmp_path,
    )
    assert out == []
    assert nfl_cache.entry_fetched_at(injury_feed.CACHE_KEY, cache_dir=tmp_path) is not None
    assert nfl_cache.get(injury_feed.CACHE_KEY, ttl_seconds=60, cache_dir=tmp_path) == []


def test_payload_shape_error_vocabulary():
    assert injury_feed.payload_shape_error({"injuries": []}) is None
    assert injury_feed.payload_shape_error(_sample_payload()) is None
    assert injury_feed.payload_shape_error({}) == "no_injuries_list"
    assert injury_feed.payload_shape_error([]) == "body_not_an_object:list"
    assert (
        injury_feed.payload_shape_error({"injuries": [{"team": {}}]})
        == "no_team_block_has_an_injuries_list"
    )


# ── the CURRENT payload shape (2026-10-26): id only in the athlete links ──────


def _current_payload():
    return json.loads(_CURRENT_FIXTURE.read_text(encoding="utf-8"))


def _rows(payload):
    """Every raw row of the fixture, as mutable references."""
    return [e for block in payload["injuries"] for e in block["injuries"]]


def _row_of(payload, name):
    (row,) = [e for e in _rows(payload) if e["athlete"]["displayName"] == name]
    return row


_TRACKED_IDS = {
    "4698113",  # Max Melton
    "4870808",  # Jeremiyah Love
    "5344782",  # Jack Strand
    "5209093",  # Michael Jerrell
    "4832793",  # Olaivavega Ioane
    "2973051",  # Taylor Moton
    "4361748",  # Anthony Johnson Jr.
    "3916409",  # Jonathan Greenard
}


def test_current_shape_fixture_has_no_athlete_id_anywhere():
    """The premise of the repair: the id is NOT in ``athlete.id`` on this shape."""
    assert all("id" not in e["athlete"] for e in _rows(_current_payload()))


def test_old_parser_logic_would_have_read_nothing_from_the_fixture():
    """Pins the diagnosis: shape check passes, every row lacks ``athlete.id``."""
    payload = _current_payload()
    assert injury_feed.payload_shape_error(payload) is None
    assert [e for e in _rows(payload) if (e["athlete"].get("id") or "").strip()] == []


def test_current_shape_fixture_parses_to_expected_rows():
    result = injury_feed.parse_espn_payload(_current_payload())
    by_id = {e.espn_athlete_id: e for e in result.entries}
    assert set(by_id) == _TRACKED_IDS
    assert [e.espn_athlete_id for e in result.entries] == [
        "4698113",
        "4870808",
        "5344782",
        "5209093",
        "4832793",
        "2973051",
        "4361748",
        "3916409",
    ]  # document order is preserved

    melton = by_id["4698113"]
    assert (melton.full_name, melton.position, melton.team_abbrev) == ("Max Melton", "CB", "ARI")
    assert melton.status == "OUT"
    assert melton.id_source == "athlete.links"
    # broad location vs specific type are both kept; body_part keeps its old meaning
    assert (melton.body_part, melton.injury_type) == ("Leg", "Knee")
    assert (melton.injury_detail, melton.injury_side) == ("Not Specified", "Not Specified")
    assert melton.returning == "2026-11-01"
    assert melton.date_reported == "2026-10-25T18:48Z"
    assert melton.source == "basic/manual"
    assert melton.description.startswith("Melton (knee) is inactive")
    assert melton.sleeper_id == ""  # the parser never resolves identity

    assert by_id["5209093"].status == "IR" and by_id["5209093"].returning == "2026-11-29"
    assert by_id["4832793"].status == "QUESTIONABLE" and by_id["4832793"].team_abbrev == "BAL"
    moton = by_id["2973051"]
    assert moton.status == "DOUBTFUL"
    assert (moton.injury_detail, moton.injury_side) == ("Fracture", "Left")
    # partial ``details`` (no detail / side keys): blank, not invented
    greenard = by_id["3916409"]
    assert (greenard.injury_type, greenard.injury_detail, greenard.injury_side) == ("Ankle", "", "")
    assert by_id["4361748"].injury_type == "Undisclosed"
    # the entry's own id is a REPORT id, never an athlete id (negative ids exist)
    assert by_id["4870808"].report_id == "-2057967"
    assert all(e.espn_athlete_id != e.report_id for e in result.entries)

    assert result.report.to_dict() == {
        "rawEntries": 10,
        "parsed": 8,
        "candidateRows": 8,
        "structuralLosses": 0,
        "skipped": {"status_active": 1, "status_untracked:SUSPENSION": 1},
        "notes": {},
    }
    assert injury_feed.payload_shape_error(_current_payload(), parsed=result) is None


def test_old_shape_still_parses():
    result = injury_feed.parse_espn_payload(_sample_payload())
    by_id = {e.espn_athlete_id: e for e in result.entries}
    assert set(by_id) == {"3918298", "4242", "5555"}
    allen = by_id["3918298"]
    assert (allen.full_name, allen.position, allen.team_abbrev, allen.status) == (
        "Josh Allen",
        "QB",
        "BUF",
        "QUESTIONABLE",
    )
    assert allen.id_source == "athlete.id"
    assert allen.body_part == "Knee" and allen.returning == "2026-11-15"
    assert allen.description == "Limited in practice"
    assert by_id["4242"].status == "DAY_TO_DAY"  # "Probable"
    assert by_id["5555"].team_abbrev == "SF"  # team from the block on the old shape
    assert by_id["5555"].returning == "Unknown"  # verbatim, not parsed
    assert result.report.skipped == {}
    # the legacy list-returning entry point is unchanged
    legacy = injury_feed._parse_espn_payload(_sample_payload())  # noqa: SLF001
    assert [e.espn_athlete_id for e in legacy] == ["3918298", "4242", "5555"]


def test_athlete_id_attr_and_links_must_agree():
    payload = _current_payload()
    row = _row_of(payload, "Max Melton")
    row["athlete"]["id"] = "4698113"  # agrees with the links -> accepted, attr wins
    result = injury_feed.parse_espn_payload(payload)
    melton = next(e for e in result.entries if e.full_name == "Max Melton")
    assert melton.id_source == "athlete.id"

    row["athlete"]["id"] = "999"  # disagrees with the links -> refused, not picked
    result = injury_feed.parse_espn_payload(payload)
    assert all(e.full_name != "Max Melton" for e in result.entries)
    assert result.report.skipped["athlete_id_ambiguous"] == 1


def test_missing_id_is_skipped_and_counted_never_taken_from_the_entry_id():
    payload = _current_payload()
    row = _row_of(payload, "Max Melton")
    row["athlete"]["links"] = []  # no id source left but the entry id (644278)
    result = injury_feed.parse_espn_payload(payload)
    assert "4698113" not in {e.espn_athlete_id for e in result.entries}
    assert "644278" not in {e.espn_athlete_id for e in result.entries}
    assert result.report.skipped["athlete_id_missing"] == 1
    assert result.report.structural_losses == 1
    assert result.report.parsed == 7


def test_ambiguous_links_are_refused():
    payload = _current_payload()
    row = _row_of(payload, "Taylor Moton")
    row["athlete"]["links"].append(
        {"rel": ["stats", "desktop"], "href": "https://www.espn.com/nfl/player/stats/_/id/1111/x"}
    )
    result = injury_feed.parse_espn_payload(payload)
    assert "2973051" not in {e.espn_athlete_id for e in result.entries}
    assert "1111" not in {e.espn_athlete_id for e in result.entries}
    assert result.report.skipped["athlete_id_ambiguous"] == 1


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda row: row.__setitem__("athlete", None), "athlete_missing"),
        (lambda row: row["athlete"].update({"id": "abc", "links": []}), "athlete_id_malformed"),
        (lambda row: row.update({"status": "", "type": {}}), "status_missing"),
    ],
)
def test_malformed_rows_are_skipped_and_counted_by_reason(mutate, reason):
    payload = _current_payload()
    mutate(_row_of(payload, "Michael Jerrell"))
    result = injury_feed.parse_espn_payload(payload)
    assert "5209093" not in {e.espn_athlete_id for e in result.entries}
    assert result.report.skipped[reason] == 1
    assert result.report.parsed == 7


def test_non_object_row_and_malformed_team_block_are_counted():
    payload = _current_payload()
    payload["injuries"][0]["injuries"].append("not an object")
    payload["injuries"].append({"id": "99", "displayName": "Broken", "injuries": "nope"})
    payload["injuries"].append("not a block")
    result = injury_feed.parse_espn_payload(payload)
    assert result.report.skipped["entry_not_object"] == 1
    assert result.report.skipped["team_block_malformed"] == 2
    assert result.report.raw_entries == 11
    assert result.report.parsed == 8  # the good rows are untouched


def test_untracked_and_healthy_statuses_are_counted_not_parsed():
    result = injury_feed.parse_espn_payload(_current_payload())
    assert "4034953" not in {e.espn_athlete_id for e in result.entries}  # Suspension
    assert "4427728" not in {e.espn_athlete_id for e in result.entries}  # Active
    assert result.report.skipped["status_active"] == 1
    assert result.report.skipped["status_untracked:SUSPENSION"] == 1
    assert result.report.structural_losses == 0  # neither is a LOSS


def test_identical_duplicate_collapses_to_one_row_and_is_counted():
    payload = _current_payload()
    row = _row_of(payload, "Max Melton")
    payload["injuries"][1]["injuries"].append(copy.deepcopy(row))  # same row, another block
    result = injury_feed.parse_espn_payload(payload)
    assert [e.espn_athlete_id for e in result.entries].count("4698113") == 1
    assert result.report.skipped["duplicate_identical_collapsed"] == 1
    assert result.report.parsed == 8


def test_conflicting_duplicates_are_all_dropped_never_picked():
    payload = _current_payload()
    row = copy.deepcopy(_row_of(payload, "Max Melton"))
    row["status"] = "Questionable"  # which copy is current is not knowable
    payload["injuries"][1]["injuries"].append(row)
    result = injury_feed.parse_espn_payload(payload)
    assert "4698113" not in {e.espn_athlete_id for e in result.entries}
    assert result.report.skipped["duplicate_conflicting"] == 2
    assert result.report.structural_losses == 2
    assert result.report.parsed == 7


def test_report_ids_do_not_make_duplicates_conflict():
    """ESPN may re-issue one report under a new row id: still the same report."""
    payload = _current_payload()
    row = copy.deepcopy(_row_of(payload, "Max Melton"))
    row["id"] = "777777"
    payload["injuries"][1]["injuries"].append(row)
    result = injury_feed.parse_espn_payload(payload)
    assert result.report.skipped["duplicate_identical_collapsed"] == 1


# ── the silent-empty alarm ──────────────────────────────────────────────────


def _strip_all_ids(payload):
    for row in _rows(payload):
        row["athlete"].pop("id", None)
        row["athlete"]["links"] = []
    return payload


def test_alarm_raw_rows_but_zero_parsed_is_drift():
    payload = _strip_all_ids(_current_payload())
    err = injury_feed.payload_shape_error(payload)
    assert err is not None
    assert err.startswith("no_injury_entries_parsed:raw=10,skipped=")
    assert "athlete_id_missing:8" in err


def test_a_report_of_only_healthy_active_rows_is_a_proven_empty_report_not_drift():
    payload = _current_payload()
    for row in _rows(payload):
        row["status"] = "Active"
    result = injury_feed.parse_espn_payload(payload)
    assert result.report.parsed == 0 and result.report.structural_losses == 0
    assert result.report.skipped == {"status_active": 10}
    assert result.report.proven_empty is True
    assert injury_feed.parse_health_error(result.report) is None
    assert injury_feed.payload_shape_error(payload, parsed=result) is None
    # ...and the proof is COUNTED, in the report the refresh logs and ledgers.
    assert result.report.to_dict()["notes"] == {injury_feed.NOTE_PROVEN_EMPTY: 10}


def test_proven_empty_needs_every_skipped_row_to_be_healthy():
    """One row of any other kind and the zero-parsed alarm stands."""
    # (a) the id source changed: rows are Out but their ids are unreadable
    ids_gone = _strip_all_ids(_current_payload())
    err = injury_feed.payload_shape_error(ids_gone)
    assert err is not None and err.startswith("no_injury_entries_parsed:raw=10")
    # (b) the status vocabulary changed: every row says something unknown
    drifted = _current_payload()
    for row in _rows(drifted):
        row["status"] = "Inactive"
    err = injury_feed.payload_shape_error(drifted)
    assert err is not None and err.startswith("no_injury_entries_parsed:raw=10")
    assert "status_untracked:INACTIVE:10" in err
    # (c) all healthy, plus one row we cannot read: not proven (a lost id may hide
    #     an injured player)
    mixed = _current_payload()
    for row in _rows(mixed):
        row["status"] = "Active"
    _rows(mixed)[0]["status"] = "Out"
    _rows(mixed)[0]["athlete"].pop("id", None)
    _rows(mixed)[0]["athlete"]["links"] = []
    result = injury_feed.parse_espn_payload(mixed)
    assert result.report.proven_empty is False and result.report.notes == {}
    assert injury_feed.parse_health_error(result.report) is not None
    # (d) all healthy plus a tolerated Suspension: still not a report we can call
    #     empty by the strict rule
    suspended = _current_payload()
    for row in _rows(suspended):
        row["status"] = "Active"
    _rows(suspended)[0]["status"] = "Suspension"
    assert injury_feed.parse_espn_payload(suspended).report.proven_empty is False
    # (e) a malformed team block beside the healthy rows
    broken_block = _current_payload()
    for row in _rows(broken_block):
        row["status"] = "Active"
    broken_block["injuries"].append("not a block")
    assert injury_feed.parse_espn_payload(broken_block).report.proven_empty is False


def test_a_proven_empty_report_is_cached_as_a_real_empty_fetch(
    monkeypatch, tmp_path, _fresh_breaker
):
    from src.nfl_data import cache as nfl_cache

    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    injury_feed.clear_last_fetch_report()
    payload = _current_payload()
    for row in _rows(payload):
        row["status"] = "Active"
    body = json.dumps(payload).encode("utf-8")
    out = injury_feed.fetch_injuries(
        _url_opener=lambda req, timeout=None: io.BytesIO(body), cache_dir=tmp_path
    )
    assert out == []
    report = injury_feed.last_fetch_report()
    assert report["outcome"] == "ok" and report["error"] is None
    assert report["parse"]["notes"] == {injury_feed.NOTE_PROVEN_EMPTY: 10}
    # proven, so the cache entry exists and a caller can tell it from a failed fetch
    assert nfl_cache.entry_fetched_at(injury_feed.CACHE_KEY, cache_dir=tmp_path) is not None


def test_alarm_does_not_fire_on_a_genuinely_empty_report():
    assert injury_feed.payload_shape_error({"injuries": []}) is None
    empty_blocks = {"injuries": [{"id": "1", "displayName": "X", "injuries": []}]}
    assert injury_feed.payload_shape_error(empty_blocks) is None


def _synthetic_current_payload(n_good: int, n_broken: int):
    def row(i, broken):
        href = f"https://www.espn.com/nfl/player/_/id/{9000 + i}/p-{i}"
        athlete = {
            "displayName": f"Player {i}",
            "position": {"abbreviation": "WR"},
            "team": {"abbreviation": "BUF"},
            "links": [] if broken else [{"href": href}],
        }
        return {"id": str(-i), "status": "Out", "date": "2026-10-26T00:00Z", "athlete": athlete}

    rows = [row(i, False) for i in range(n_good)] + [row(n_good + j, True) for j in range(n_broken)]
    return {"injuries": [{"id": "2", "displayName": "Buffalo Bills", "injuries": rows}]}


def test_alarm_parse_loss_fraction_boundaries():
    # 3 of 30 lost = exactly 10%: tolerated.  4 of 30 = 13.3%: drift.
    ok = injury_feed.parse_espn_payload(_synthetic_current_payload(27, 3))
    assert ok.report.parsed == 27 and ok.report.structural_losses == 3
    assert injury_feed.parse_health_error(ok.report) is None
    bad = injury_feed.parse_espn_payload(_synthetic_current_payload(26, 4))
    err = injury_feed.parse_health_error(bad.report)
    assert err is not None and err.startswith("parse_loss_above_10pct:4/30,skipped=")


def _status_mix_payload(n_good: int, **other_status_counts: int):
    """``n_good`` readable ``Out`` rows plus N rows per extra status (readable ids)."""

    def row(i, status):
        href = f"https://www.espn.com/nfl/player/_/id/{9000 + i}/p-{i}"
        athlete = {
            "displayName": f"Player {i}",
            "position": {"abbreviation": "WR"},
            "team": {"abbreviation": "BUF"},
            "links": [{"href": href}],
        }
        return {"id": str(-i), "status": status, "date": "2026-10-26T00:00Z", "athlete": athlete}

    rows = [row(i, "Out") for i in range(n_good)]
    n = n_good
    for status, count in other_status_counts.items():
        for _ in range(count):
            rows.append(row(n, status.replace("_", " ")))
            n += 1
    return {"injuries": [{"id": "2", "displayName": "Buffalo Bills", "injuries": rows}]}


def test_unknown_statuses_count_toward_the_loss_rule_but_suspension_does_not():
    # 3 unknown-status rows of 30 candidates = exactly 10%: tolerated (like 3 lost ids).
    ok = injury_feed.parse_espn_payload(_status_mix_payload(27, Inactive=3))
    assert ok.report.skipped == {"status_untracked:INACTIVE": 3}
    assert ok.report.parsed == 27 and ok.report.structural_losses == 3
    assert ok.report.candidate_rows == 30
    assert injury_feed.parse_health_error(ok.report) is None
    # 4 of 30 = 13.3%: a renamed status vocabulary is drift, not a quiet league.
    bad = injury_feed.parse_espn_payload(_status_mix_payload(26, Inactive=4))
    assert bad.report.structural_losses == 4
    err = injury_feed.parse_health_error(bad.report)
    assert err is not None and err.startswith("parse_loss_above_10pct:4/30,skipped=")
    assert "status_untracked:INACTIVE:4" in err
    # The same four rows as SUSPENSION are an expected non-injury: no loss at all.
    fine = injury_feed.parse_espn_payload(_status_mix_payload(26, Suspension=4))
    assert fine.report.skipped == {"status_untracked:SUSPENSION": 4}
    assert fine.report.structural_losses == 0
    assert fine.report.candidate_rows == 26
    assert injury_feed.parse_health_error(fine.report) is None
    # Many suspensions never trip the rule however large their share.
    many = injury_feed.parse_espn_payload(_status_mix_payload(25, Suspension=25))
    assert many.report.structural_losses == 0
    assert injury_feed.parse_health_error(many.report) is None


def test_every_untracked_status_but_the_tolerated_ones_is_a_structural_loss():
    assert injury_feed.is_structural_loss_reason("status_untracked:INACTIVE") is True
    assert injury_feed.is_structural_loss_reason("status_untracked:") is True
    assert injury_feed.is_structural_loss_reason("status_untracked:SUSPENSION") is False
    assert injury_feed.is_structural_loss_reason("status_active") is False
    assert injury_feed.is_structural_loss_reason("athlete_id_missing") is True
    assert injury_feed.is_structural_loss_reason("duplicate_identical_collapsed") is False
    assert injury_feed.is_structural_loss_reason("team_block_malformed") is False


def test_alarm_parse_loss_fraction_is_not_judged_below_the_floor():
    small = injury_feed.parse_espn_payload(_synthetic_current_payload(4, 2))  # 33% of 6 rows
    assert injury_feed.parse_health_error(small.report) is None  # noise, not drift


def test_zero_parsed_alarm_is_a_failed_fetch_not_a_cached_empty_report(
    monkeypatch, tmp_path, _fresh_breaker
):
    from src.nfl_data import cache as nfl_cache

    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    injury_feed.clear_last_fetch_report()
    body = json.dumps(_strip_all_ids(_current_payload())).encode("utf-8")
    out = injury_feed.fetch_injuries(
        _url_opener=lambda req, timeout=None: io.BytesIO(body), cache_dir=tmp_path
    )
    assert out == []
    assert nfl_cache.entry_fetched_at(injury_feed.CACHE_KEY, cache_dir=tmp_path) is None
    report = injury_feed.last_fetch_report()
    assert report["outcome"] == "drift"
    assert report["error"].startswith("no_injury_entries_parsed:raw=10")
    assert report["parse"]["parsed"] == 0


def test_current_shape_through_fetch_injuries_parses_caches_and_round_trips(
    monkeypatch, tmp_path, _fresh_breaker
):
    from src.nfl_data import cache as nfl_cache

    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    injury_feed.clear_last_fetch_report()
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        return io.BytesIO(_CURRENT_FIXTURE.read_bytes())

    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert {e.espn_athlete_id for e in out} == _TRACKED_IDS
    assert injury_feed.last_fetch_report()["outcome"] == "ok"
    assert nfl_cache.entry_fetched_at(injury_feed.CACHE_KEY, cache_dir=tmp_path) is not None
    again = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert len(calls) == 1  # served from the cache
    assert again == out  # the cached dict round-trips every field, new ones included


def test_a_v1_cache_entry_written_by_the_id_blind_parser_is_never_read_back(
    monkeypatch, tmp_path, _fresh_breaker
):
    """The old parser cached ``[]`` for a body full of rows.  The key moved to v2."""
    from src.nfl_data import cache as nfl_cache

    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    nfl_cache.put("espn_injuries:v1", [], cache_dir=tmp_path)
    assert injury_feed.CACHE_KEY == "espn_injuries:v2"
    out = injury_feed.fetch_injuries(
        _url_opener=lambda req, timeout=None: io.BytesIO(_CURRENT_FIXTURE.read_bytes()),
        cache_dir=tmp_path,
    )
    assert len(out) == 8


def test_entry_dict_round_trip_accepts_a_pre_2026_10_26_cache_row():
    legacy = {
        "espnAthleteId": "1",
        "fullName": "A B",
        "position": "WR",
        "teamAbbrev": "BUF",
        "status": "OUT",
        "bodyPart": "Knee",
        "description": "",
        "dateReported": "",
        "returning": "",
    }
    e = injury_feed.entry_from_dict(legacy)
    assert e.espn_athlete_id == "1" and e.injury_type == "" and e.sleeper_id == ""
    assert injury_feed.entry_from_dict(e.to_dict()) == e


def test_new_injury_signal_reason_prefers_the_specific_injury_type():
    e = injury_feed.entry_from_dict(
        {"espnAthleteId": "1", "fullName": "A B", "status": "OUT", "bodyPart": "Leg"}
    )
    e2 = injury_feed.entry_from_dict(
        {
            "espnAthleteId": "1",
            "fullName": "A B",
            "status": "OUT",
            "bodyPart": "Leg",
            "injuryType": "Knee",
            "sleeperId": "42",
        }
    )
    assert "(Leg)" in injury_feed.diff_for_signals([], [e])[0]["reason"]
    sig = injury_feed.diff_for_signals([], [e2])[0]
    assert "(Knee)" in sig["reason"] and sig["sleeperId"] == "42"
