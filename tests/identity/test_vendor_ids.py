"""VID: the append-only vendor-id → canonical player map (V2.1 §3.7).

Registered rule: entries only from (a) vendor-published Sleeper ids, or (b)
VERIFIED joins (exact name rung, position family AND team agree) seen on ≥ 2
content-distinct datasets of the same source; a conflict is never resolved
automatically — the id becomes UNRESOLVED.  Synthetic directory only.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.identity import resolution as r
from src.identity import vendor_ids as v

DIRECTORY = {
    "9221": {
        "full_name": "Jahmyr Gibbs",
        "position": "RB",
        "team": "DET",
        "fantasy_positions": ["RB"],
    },
    "4881": {"full_name": "Josh Allen", "position": "QB", "team": "BUF"},
    "4229": {
        "full_name": "Josh Allen",
        "position": "LB",
        "team": "JAX",
        "fantasy_positions": ["LB", "DL"],
    },
    "7001": {"full_name": "Twin Name", "position": "WR", "team": "NYJ"},
    "7002": {"full_name": "Twin Name", "position": "WR", "team": "NYJ"},
}
NS = "provider:keepTradeCut"


@pytest.fixture(scope="module")
def index():
    return r.build_sleeper_index(DIRECTORY)


def _obs(
    vid,
    sid,
    basis=v.BASIS_VERIFIED_JOIN,
    source="ktcCrowdSfTep",
    h="h1",
    at="2026-10-21T00:00:00+00:00",
):
    return v.VidObservation(NS, vid, sid, basis, source, h, at)


# ── (b) verified join ──────────────────────────────────────────────────


def test_verified_join_needs_exact_name_family_and_team(index):
    assert v.verified_join(index, raw_name="Jahmyr Gibbs", position="RB", team="DET") == "9221"
    assert v.verified_join(index, raw_name="Jahmyr Gibbs", position="WR", team="DET") is None
    assert v.verified_join(index, raw_name="Jahmyr Gibbs", position="RB", team="DAL") is None
    assert v.verified_join(index, raw_name="Jahmyr Gibbs", position="RB", team="") is None
    assert v.verified_join(index, raw_name="Jahmyr Gibbs", position="", team="DET") is None
    assert (
        v.verified_join(index, raw_name="J. Gibbs", position="RB", team="DET") is None
    )  # no fuzzy


def test_verified_join_separates_homonyms_only_by_family_and_team(index):
    assert v.verified_join(index, raw_name="Josh Allen", position="QB", team="BUF") == "4881"
    assert v.verified_join(index, raw_name="Josh Allen", position="DE", team="JAX") == "4229"
    assert v.verified_join(index, raw_name="Twin Name", position="WR", team="NYJ") is None


def test_one_dataset_is_insufficient_two_distinct_datasets_map(index):
    m = v.VendorIdMap([_obs("1415", "9221", h="h1")])
    assert m.state(NS, "1415") == v.STATE_INSUFFICIENT and m.resolve(NS, "1415") is None
    m = v.VendorIdMap([_obs("1415", "9221", h="h1"), _obs("1415", "9221", h="h1")])
    assert m.resolve(NS, "1415") is None  # a re-read of one dataset is one observation
    m = v.VendorIdMap([_obs("1415", "9221", h="h1"), _obs("1415", "9221", h="h2")])
    assert m.resolve(NS, "1415") == "9221"


def test_two_modes_of_one_capture_never_confirm_each_other():
    m = v.VendorIdMap(
        [
            _obs("1415", "9221", source="ktcCrowdSfTep", h="a"),
            _obs("1415", "9221", source="ktcTradesSfTep", h="b"),
        ]
    )
    assert m.state(NS, "1415") == v.STATE_INSUFFICIENT


# ── (a) vendor-published Sleeper id ────────────────────────────────────


def test_vendor_published_sleeper_id_maps_at_once_if_it_names_a_player(index):
    row = {"name": "Jahmyr Gibbs", "vendorId": "77", "sleeperId": "9221"}
    obs = v.observation_for_row(
        source_key="pfkDynasty", row=row, index=index, dataset_hash="x", observed_at="t"
    )
    assert obs.basis == v.BASIS_VENDOR_SLEEPER_ID and obs.sleeper_id == "9221"
    assert v.VendorIdMap([obs]).resolve(obs.namespace, "77") == "9221"
    nobody = {**row, "sleeperId": "123456"}
    assert (
        v.observation_for_row(
            source_key="pfkDynasty", row=nobody, index=index, dataset_hash="x", observed_at="t"
        )
        is None
    )
    assert (
        v.observation_for_row(
            source_key="pfkDynasty",
            row={"name": "X"},
            index=index,
            dataset_hash="x",
            observed_at="t",
        )
        is None
    )


# ── conflicts are never resolved automatically ─────────────────────────


def test_a_conflict_is_unresolved_for_good():
    m = v.VendorIdMap(
        [
            _obs("1415", "9221", h="h1"),
            _obs("1415", "9221", h="h2"),
            _obs("1415", "4881", basis=v.BASIS_VENDOR_SLEEPER_ID, h="h3"),
        ]
    )
    assert m.state(NS, "1415") == v.STATE_CONFLICT
    assert m.resolve(NS, "1415") is None
    assert m.resolver_for("ktcCrowdSfTep")("1415") is None
    assert m.census()[v.STATE_CONFLICT] == 1


def test_namespace_is_the_provider_else_the_source():
    assert v.namespace_for("ktc") == v.namespace_for("ktcCrowdSfTep") == NS
    assert v.namespace_for("no_such_source_key") == "source:no_such_source_key"


# ── append-only store, ARRIVING reads ─────────────────────────────────


def test_store_appends_only_state_changing_lines_and_never_rewrites(tmp_path):
    store = tmp_path / v.STORE_REL
    assert v.append_observations(store, [_obs("1415", "9221", h="h1")]) == 1
    first = store.read_text(encoding="utf-8")
    # a re-read of the same dataset, then a confirming dataset, then a third
    # dataset that changes nothing
    assert v.append_observations(store, [_obs("1415", "9221", h="h1")]) == 0
    assert v.append_observations(store, [_obs("1415", "9221", h="h2")]) == 1
    assert v.append_observations(store, [_obs("1415", "9221", h="h3")]) == 0
    assert store.read_text(encoding="utf-8").startswith(first)
    # a conflicting player is always recorded
    assert v.append_observations(store, [_obs("1415", "4881", h="h4")]) == 1
    assert v.VendorIdMap.load(store).state(NS, "1415") == v.STATE_CONFLICT


def test_as_of_reads_only_strictly_earlier_observations(tmp_path):
    store = tmp_path / v.STORE_REL
    v.append_observations(
        store,
        [
            _obs("1415", "9221", h="h1", at="2026-10-21T00:00:00+00:00"),
            _obs("1415", "9221", h="h2", at="2026-10-22T00:00:00+00:00"),
        ],
    )
    at = lambda s: datetime.fromisoformat(s)  # noqa: E731
    assert (
        v.VendorIdMap.load(store, as_of=at("2026-10-22T00:00:00+00:00")).resolve(NS, "1415") is None
    )
    assert (
        v.VendorIdMap.load(store, as_of=at("2026-10-22T00:00:01+00:00")).resolve(NS, "1415")
        == "9221"
    )
    assert v.VendorIdMap.load(tmp_path / "missing.jsonl").observation_count == 0


def test_a_torn_tail_line_is_skipped_never_guessed(tmp_path):
    store = tmp_path / v.STORE_REL
    v.append_observations(store, [_obs("1415", "9221", h="h1")])
    with store.open("a", encoding="utf-8") as f:
        f.write('{"namespace": "provider:keepTradeCut", "vendor_')
    assert v.VendorIdMap.load(store).observation_count == 1


# ── the recorder over a site_raw directory ─────────────────────────────


def _ktc_csv(rows):
    return "name,value,rank,player_id,position,team\n" + "".join(
        f"{n},{val},{rk},{pid},{pos},{team}\n" for n, val, rk, pid, pos, team in rows
    )


def test_recorder_folds_vendor_id_boards_and_skips_others(tmp_path, index):
    site = tmp_path / "site_raw"
    site.mkdir()
    (site / "ktcCrowdSfTep.csv").write_text(
        _ktc_csv(
            [("Jahmyr Gibbs", 9000, 1, 1415, "RB", "DET"), ("Twin Name", 100, 2, 5, "WR", "NYJ")]
        ),
        encoding="utf-8",
    )
    (site / "fantasyCalc.csv").write_text(
        "name,value,rank\nJahmyr Gibbs,9000,1\n", encoding="utf-8"
    )
    store = tmp_path / v.STORE_REL
    out = v.record_from_site_raw(
        site, index=index, store_path=store, observed_at="2026-10-21T00:00:00+00:00"
    )
    assert set(out["sources"]) == {"ktcCrowdSfTep"}
    assert out["sources"]["ktcCrowdSfTep"]["observations"] == 1  # homonyms never map
    assert out["appended"] == 1
    # the same dataset with identity columns reordered is the same dataset
    (site / "ktcCrowdSfTep.csv").write_text(
        "name,value,rank,player_id,team,position\nTwin Name,100,2,5,NYJ,WR\nJahmyr Gibbs,9000,1,1415,DET,RB\n",
        encoding="utf-8",
    )
    again = v.record_from_site_raw(
        site, index=index, store_path=store, observed_at="2026-10-21T02:00:00+00:00"
    )
    assert (
        again["sources"]["ktcCrowdSfTep"]["datasetHash"]
        == out["sources"]["ktcCrowdSfTep"]["datasetHash"]
    )
    assert again["appended"] == 0
    (site / "ktcCrowdSfTep.csv").write_text(
        _ktc_csv([("Jahmyr Gibbs", 9050, 1, 1415, "RB", "DET")]), encoding="utf-8"
    )
    third = v.record_from_site_raw(
        site, index=index, store_path=store, observed_at="2026-10-21T04:00:00+00:00"
    )
    assert third["appended"] == 1
    assert v.VendorIdMap.load(store).resolve(NS, "1415") == "9221"


def test_recorder_without_a_directory_records_nothing(tmp_path):
    out = v.record_from_site_raw(
        tmp_path, index=None, store_path=tmp_path / "s.jsonl", observed_at="t"
    )
    assert out["skipped"] == "identity_directory_unavailable" and out["appended"] == 0


def test_observed_at_is_utc_comparable():
    obs = _obs("1", "9221", at="2026-10-21T02:00:00+02:00")
    assert v._parse_instant(obs.observed_at) == datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
