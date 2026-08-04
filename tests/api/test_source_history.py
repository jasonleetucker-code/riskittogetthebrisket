"""Tests for per-source value history persistence + backfill."""

from __future__ import annotations

import json

import pytest

from src.api import source_history


@pytest.fixture()
def path(tmp_path):
    return tmp_path / "source_value_history.jsonl"


def _make_contract(players, *, date="2026-04-23"):
    """Build a minimal contract with ``playersArray`` rows.  Each
    player is given both ``sourceRankMeta.valueContribution`` and a
    ``canonicalSiteValues`` fallback so tests cover both code paths.
    """
    arr = []
    for entry in players:
        row = {
            "displayName": entry["name"],
            "canonicalName": entry["name"],
            "position": entry.get("pos", "WR"),
            "assetClass": entry.get("assetClass", "offense"),
            "rankDerivedValue": entry.get("blended"),
            "canonicalConsensusRank": entry.get("rank"),
        }
        if "sources" in entry:
            row["sourceRankMeta"] = {
                k: {"valueContribution": v} for k, v in entry["sources"].items()
            }
        if "canonicalSites" in entry:
            row["canonicalSiteValues"] = entry["canonicalSites"]
        arr.append(row)
    return {"date": date, "playersArray": arr}


def test_append_then_load(path):
    contract = _make_contract(
        [
            {
                "name": "Malik Nabers",
                "blended": 8154,
                "rank": 17,
                "sources": {"ktcSfTep": 7844, "fp_sf": 8580, "dlf_sf": 9720},
            },
        ],
        date="2026-04-23",
    )
    assert source_history.append_snapshot(contract, date="2026-04-23", path=path) is True

    hist = source_history.load_player_history("Malik Nabers", path=path)
    assert hist["dates"] == ["2026-04-23"]
    assert hist["blended"][0]["value"] == 8154
    assert hist["blended"][0]["rank"] == 17
    assert hist["blended"][0]["derived"] is False
    assert hist["sources"]["ktcSfTep"][0]["value"] == 7844
    assert hist["sources"]["fp_sf"][0]["value"] == 8580


def test_dedupe_same_date(path):
    # Two writes on the same date — the second wins.
    source_history.append_snapshot(
        _make_contract(
            [{"name": "A", "blended": 1000, "sources": {"ktcSfTep": 900}}], date="2026-04-23"
        ),
        path=path,
    )
    source_history.append_snapshot(
        _make_contract(
            [{"name": "A", "blended": 1200, "sources": {"ktcSfTep": 1100}}], date="2026-04-23"
        ),
        path=path,
    )
    hist = source_history.load_player_history("A", path=path)
    assert len(hist["blended"]) == 1
    assert hist["blended"][0]["value"] == 1200
    assert hist["sources"]["ktcSfTep"][0]["value"] == 1100


def test_multiple_dates_sorted(path):
    # NOTE: ``append_snapshot`` uses ``_today_utc()`` when no ``date=``
    # kwarg is passed (it never reads ``contract['date']`` — server.py
    # relies on the wall clock).  Tests must pass ``date=`` explicitly
    # to simulate historical writes.
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1000, "sources": {"ktcSfTep": 900}}]),
        date="2026-04-22",
        path=path,
    )
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1050, "sources": {"ktcSfTep": 950}}]),
        date="2026-04-23",
        path=path,
    )
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1100, "sources": {"ktcSfTep": 1000}}]),
        date="2026-04-24",
        path=path,
    )
    hist = source_history.load_player_history("A", path=path)
    assert hist["dates"] == ["2026-04-22", "2026-04-23", "2026-04-24"]
    assert [e["value"] for e in hist["blended"]] == [1000, 1050, 1100]


def test_retention_trims_to_max_snapshots(path):
    # Simulate 200 DISTINCT dates, retention = 180.  Use a deterministic
    # iteration that avoids the Jan/Feb modulo collision an earlier
    # version of this test had.
    from datetime import date as _date, timedelta

    base = _date(2026, 1, 1)
    for i in range(200):
        d = (base + timedelta(days=i)).isoformat()
        source_history.append_snapshot(
            _make_contract([{"name": "A", "blended": 1000 + i, "sources": {"ktcSfTep": 900 + i}}]),
            date=d,
            path=path,
            max_snapshots=180,
        )
    with path.open("r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 180


def test_case_insensitive_name_lookup(path):
    source_history.append_snapshot(
        _make_contract(
            [{"name": "Ja'Marr Chase", "blended": 9999, "sources": {"ktcSfTep": 9900}}],
            date="2026-04-23",
        ),
        path=path,
    )
    hist = source_history.load_player_history("ja'marr chase", path=path)
    assert hist["blended"][0]["value"] == 9999
    assert hist["sources"]["ktcSfTep"][0]["value"] == 9900


def test_derived_blend_from_median_when_blended_missing(path):
    # No ``rankDerivedValue`` on the row — loader should synthesize a
    # blended entry from the per-source median.
    contract = _make_contract(
        [{"name": "X", "sources": {"ktcSfTep": 7000, "fp_sf": 7500, "dlf_sf": 8000}}],
        date="2026-04-23",
    )
    # Strip the blended stamp.
    for row in contract["playersArray"]:
        row.pop("rankDerivedValue", None)
    source_history.append_snapshot(contract, path=path)
    hist = source_history.load_player_history("X", path=path)
    assert hist["blended"][0]["derived"] is True
    # Median of 7000/7500/8000 is 7500.
    assert hist["blended"][0]["value"] == 7500


def test_canonical_sites_fallback(path):
    # Row has no sourceRankMeta, only canonicalSiteValues — the
    # legacy export shape.
    contract = _make_contract(
        [{"name": "L", "canonicalSites": {"ktcSfTep": 8100, "fp_sf": 8400}}],
        date="2026-04-23",
    )
    source_history.append_snapshot(contract, path=path)
    hist = source_history.load_player_history("L", path=path)
    assert hist["sources"]["ktcSfTep"][0]["value"] == 8100
    assert hist["sources"]["fp_sf"][0]["value"] == 8400


def test_asset_class_disambiguation(path):
    # Two players with the same name, different asset classes — the
    # composite key prevents collision.  ``asset_class`` param picks
    # the one the caller wants.
    contract = _make_contract(
        [
            {
                "name": "James Williams",
                "blended": 5000,
                "assetClass": "offense",
                "sources": {"ktcSfTep": 5200},
            },
            {
                "name": "James Williams",
                "blended": 3000,
                "assetClass": "idp",
                "sources": {"ktcSfTep": 3100},
            },
        ],
        date="2026-04-23",
    )
    source_history.append_snapshot(contract, path=path)
    off = source_history.load_player_history("James Williams", asset_class="offense", path=path)
    idp = source_history.load_player_history("James Williams", asset_class="idp", path=path)
    assert off["blended"][0]["value"] == 5000
    assert idp["blended"][0]["value"] == 3000


def test_missing_player_returns_empty(path):
    source_history.append_snapshot(
        _make_contract([{"name": "A", "blended": 1000, "sources": {"ktcSfTep": 900}}]),
        path=path,
    )
    hist = source_history.load_player_history("Unknown", path=path)
    assert hist["dates"] == []
    assert hist["blended"] == []
    assert hist["sources"] == {}


def test_backfill_from_exports_merges_with_existing(tmp_path, path):
    # Seed an existing snapshot for 2026-04-23 via the live path.
    source_history.append_snapshot(
        _make_contract(
            [{"name": "A", "blended": 9999, "sources": {"ktcSfTep": 9000}}], date="2026-04-23"
        ),
        date="2026-04-23",
        path=path,
    )
    # Now point backfill at a historical export dated earlier.
    export = tmp_path / "dynasty_data_2026-04-20.json"
    export.write_text(
        json.dumps(
            {
                "date": "2026-04-20",
                "players": {
                    "A": {
                        "ktcSfTep": 8000,
                        "dlfSf": 8500,
                        "_canonicalSiteValues": {"ktcSfTep": 8000, "dlfSf": 8500},
                    }
                },
            }
        )
    )

    written = source_history.backfill_from_exports([export], path=path)
    assert written == 1
    hist = source_history.load_player_history("A", path=path)
    dates = [b["date"] for b in hist["blended"]]
    assert "2026-04-20" in dates
    # Newer snapshot preserved verbatim.
    latest = [b for b in hist["blended"] if b["date"] == "2026-04-23"][0]
    assert latest["value"] == 9999


def test_append_returns_false_for_empty_contract(path):
    assert (
        source_history.append_snapshot({"date": "2026-04-23", "playersArray": []}, path=path)
        is False
    )
    assert not path.exists() or path.read_text() == ""


# ── _derive_source_ranks ──────────────────────────────────────────────


def test_derive_source_ranks_assigns_ranks_from_value_sort():
    """The backfill path needs to recover per-source rank history
    from old snapshots that only persisted per-source values (the
    ``sourceRanks`` schema field landed 2026-04-29).  Verify the
    derivation: highest value → rank 1, second-highest → rank 2,
    etc., per source.
    """
    entries = {
        "A": {"sources": {"ktcSfTep": 9000, "dlfSf": 7000}},
        "B": {"sources": {"ktcSfTep": 8500, "dlfSf": 9500}},
        "C": {"sources": {"ktcSfTep": 7500, "dlfSf": 8000}},
    }
    source_history._derive_source_ranks(entries)
    assert entries["A"]["sourceRanks"] == {"ktcSfTep": 1, "dlfSf": 3}
    assert entries["B"]["sourceRanks"] == {"ktcSfTep": 2, "dlfSf": 1}
    assert entries["C"]["sourceRanks"] == {"ktcSfTep": 3, "dlfSf": 2}


def test_derive_source_ranks_preserves_native_stamps():
    """When a row already carries a real (contract-stamped)
    ``sourceRanks`` block, the derivation pass MUST NOT overwrite
    it.  Fresh contracts go through the live append path which
    leaves derive_ranks=False; this guard is defense-in-depth for
    the case where someone runs the backfill over a JSONL that
    was already partially populated by the live path."""
    entries = {
        "A": {
            "sources": {"ktcSfTep": 5000},
            "sourceRanks": {"ktcSfTep": 99},  # native, sentinel
        },
        "B": {"sources": {"ktcSfTep": 9000}},  # higher value, no native rank
    }
    source_history._derive_source_ranks(entries)
    # A's native sentinel survives.
    assert entries["A"]["sourceRanks"]["ktcSfTep"] == 99
    # B gets a derived rank where it had none.
    assert entries["B"]["sourceRanks"]["ktcSfTep"] == 1


def test_derive_source_ranks_skips_zero_or_missing_values():
    """Players with missing/zero per-source value don't get a
    derived rank for that source — keeps the chart honest about
    coverage."""
    entries = {
        "A": {"sources": {"ktcSfTep": 9000, "dlfSf": 7000}},
        "B": {"sources": {"ktcSfTep": 8500}},  # no DLF SF coverage
        "C": {"sources": {"dlfSf": 9500}},  # no KTC coverage
    }
    source_history._derive_source_ranks(entries)
    assert entries["A"]["sourceRanks"]["ktcSfTep"] == 1
    assert entries["A"]["sourceRanks"]["dlfSf"] == 2
    assert entries["B"]["sourceRanks"]["ktcSfTep"] == 2
    assert "dlfSf" not in entries["B"].get("sourceRanks", {})
    assert "ktcSfTep" not in entries["C"].get("sourceRanks", {})
    assert entries["C"]["sourceRanks"]["dlfSf"] == 1


def test_backfill_derives_ranks_for_legacy_dict_export(tmp_path, path):
    """End-to-end: ``backfill_from_exports`` against an old-shape
    export with the legacy ``players`` dict (no native sourceRanks)
    should populate the derived rank history so the chart can draw
    per-source rank lines for historical dates."""
    export = tmp_path / "dynasty_data_2026-04-15.json"
    export.write_text(
        json.dumps(
            {
                "date": "2026-04-15",
                "players": {
                    "Star WR": {
                        "ktcSfTep": 9500,
                        "dlfSf": 9000,
                        "_canonicalSiteValues": {"ktcSfTep": 9500, "dlfSf": 9000},
                    },
                    "Mid WR": {
                        "ktcSfTep": 7000,
                        "dlfSf": 7500,
                        "_canonicalSiteValues": {"ktcSfTep": 7000, "dlfSf": 7500},
                    },
                    "Bench WR": {
                        "ktcSfTep": 4000,
                        "dlfSf": 4500,
                        "_canonicalSiteValues": {"ktcSfTep": 4000, "dlfSf": 4500},
                    },
                },
            }
        )
    )
    source_history.backfill_from_exports([export], path=path)
    # Verify the JSONL stamps sourceRanks for the legacy export.
    raw = path.read_text().strip().splitlines()
    assert len(raw) == 1
    snap = json.loads(raw[0])
    # Keys are ``"<displayName>::<assetClass>"`` per ``_player_key``;
    # legacy dict rows without a position resolve to ``"unknown"``.
    star_entry = next(v for k, v in snap["players"].items() if k.startswith("Star WR"))
    assert star_entry["sourceRanks"]["ktcSfTep"] == 1
    assert star_entry["sourceRanks"]["dlfSf"] == 1
    mid_entry = next(v for k, v in snap["players"].items() if k.startswith("Mid WR"))
    assert mid_entry["sourceRanks"]["ktcSfTep"] == 2
    assert mid_entry["sourceRanks"]["dlfSf"] == 2
    bench_entry = next(v for k, v in snap["players"].items() if k.startswith("Bench WR"))
    assert bench_entry["sourceRanks"]["ktcSfTep"] == 3
    assert bench_entry["sourceRanks"]["dlfSf"] == 3


def test_scope_filter_drops_idp_source_for_offense_player(path):
    """An offense WR that somehow carries an ``draftSharksIdp`` value /
    rank in the contract row (e.g. a downstream cross-market leak)
    must NOT surface in the per-source history.  IDP-scope sources
    only legitimately rank IDP players; an offense-classed snapshot
    entry has those keys filtered both at write time
    (``_extract_player_entry``) and at read time
    (``load_player_history``).
    """
    contract = _make_contract(
        [
            {
                "name": "Ja'Marr Chase",
                "pos": "WR",
                "assetClass": "offense",
                "blended": 9700,
                "rank": 5,
                # Both an offense source (legitimate) and an IDP-scope
                # source (illegitimate leak) — the filter must drop
                # only the IDP-scope key.
                "sources": {"ktcSfTep": 9900, "draftSharksIdp": 1500},
            },
        ],
        date="2026-05-04",
    )
    assert source_history.append_snapshot(contract, date="2026-05-04", path=path) is True

    # Read back: only the offense source survives in the history.
    hist = source_history.load_player_history("Ja'Marr Chase", path=path)
    assert "ktcSfTep" in hist["sources"]
    assert "draftSharksIdp" not in hist["sources"]

    # Snapshot on disk is also clean — write-time filter prevents the
    # IDP-scope contribution from ever landing in the JSONL.
    raw = path.read_text().strip().splitlines()
    snap = json.loads(raw[0])
    chase_entry = next(v for k, v in snap["players"].items() if k.startswith("Ja'Marr Chase"))
    assert "draftSharksIdp" not in chase_entry["sources"]
    assert "ktcSfTep" in chase_entry["sources"]


def test_scope_filter_drops_offense_source_for_idp_player(path):
    """Symmetric guard: an IDP player that picks up an offense-scope
    source value (e.g. ``dlfSf``) must have it filtered out.  IDP
    sources like IDPTradeCalc that declare ``extra_scopes`` covering
    offense remain valid for both asset classes; pure-offense scopes
    do not.
    """
    contract = _make_contract(
        [
            {
                "name": "Carson Schwesinger",
                "pos": "LB",
                "assetClass": "idp",
                "blended": 5500,
                "rank": 80,
                "sources": {"draftSharksIdp": 4400, "dlfSf": 9000},
            },
        ],
        date="2026-05-04",
    )
    source_history.append_snapshot(contract, date="2026-05-04", path=path)
    hist = source_history.load_player_history("Carson Schwesinger", path=path)
    assert "draftSharksIdp" in hist["sources"]
    assert "dlfSf" not in hist["sources"]


def test_scope_filter_read_time_strips_legacy_polluted_snapshot(path):
    """Old snapshots written before the write-time filter could carry
    scope-mismatched per-source entries.  ``load_player_history``
    must drop them at read time so the chart never surfaces a
    ``draftSharksIdp`` rank for a WR even when the JSONL on disk
    has the legacy pollution.
    """
    polluted = {
        "date": "2026-03-23",
        "players": {
            "Ja'Marr Chase::offense": {
                "blended": 9550,
                "blendedRank": 5,
                "sources": {"ktcSfTep": 9849, "draftSharksIdp": 1552},
                "sourceRanks": {"ktcSfTep": 5, "draftSharksIdp": 414},
            }
        },
    }
    path.write_text(json.dumps(polluted) + "\n")
    hist = source_history.load_player_history("Ja'Marr Chase", path=path)
    assert "ktcSfTep" in hist["sources"]
    assert "draftSharksIdp" not in hist["sources"]
    assert "ktcSfTep" in hist["sourceRanks"]
    assert "draftSharksIdp" not in hist["sourceRanks"]


def test_scope_filter_preserves_unknown_source_keys(path):
    """Source keys not present in the registry (retired sources,
    custom keys from old exports) pass through unchanged so legacy
    history isn't silently erased.  Only registry-known keys whose
    scope mismatches the player's asset class get dropped.
    """
    polluted = {
        "date": "2026-03-23",
        "players": {
            "Ja'Marr Chase::offense": {
                "blended": 9550,
                "sources": {"someRetiredKey": 8000, "draftSharksIdp": 1500},
                "sourceRanks": {"someRetiredKey": 7, "draftSharksIdp": 414},
            }
        },
    }
    path.write_text(json.dumps(polluted) + "\n")
    hist = source_history.load_player_history("Ja'Marr Chase", path=path)
    # Unknown key survives — preserves legacy data we can't classify.
    assert "someRetiredKey" in hist["sources"]
    # Registry-known IDP-scope key is filtered for the offense entry.
    assert "draftSharksIdp" not in hist["sources"]


def test_scope_filter_keeps_cross_scope_source_for_both_asset_classes(path):
    """``idpTradeCalc`` declares ``scope=overall_idp`` plus
    ``extra_scopes=[overall_offense]`` — it's a cross-market
    source that legitimately ranks both offense and IDP.  The
    scope filter must accept it for both asset classes.
    """
    contract = _make_contract(
        [
            {
                "name": "Top WR",
                "pos": "WR",
                "assetClass": "offense",
                "blended": 9000,
                "sources": {"idpTradeCalc": 8800},
            },
            {
                "name": "Top LB",
                "pos": "LB",
                "assetClass": "idp",
                "blended": 5000,
                "sources": {"idpTradeCalc": 4900},
            },
        ],
        date="2026-05-04",
    )
    source_history.append_snapshot(contract, path=path)
    off = source_history.load_player_history("Top WR", path=path)
    idp = source_history.load_player_history("Top LB", path=path)
    assert "idpTradeCalc" in off["sources"]
    assert "idpTradeCalc" in idp["sources"]


def test_retired_ktc_filtered_from_chart_at_write_and_read(path):
    """``ktc`` (standard KTC SF) was retired from the blend in favour of
    ``ktcSfTep`` (KTC SF + TE++) but its raw value is still loaded into
    the contract so the trade-page arbitrage finder + per-source winner
    row can keep displaying both side-by-side.  The per-player
    value-history chart, however, would double-show "KTC" since the
    legend collapses both keys to the same compact label.

    Both write-time (``_extract_player_entry``) and read-time
    (``load_player_history``) filters drop ``ktc`` so the chart is
    deduplicated immediately, including for the 180-day backwards
    window that has historical ``ktc`` entries.
    """
    # Write-time: row carries both ``ktc`` (in canonicalSites + meta)
    # and ``ktcSfTep`` — only ``ktcSfTep`` should land in the snapshot.
    contract = {
        "date": "2026-05-05",
        "playersArray": [
            {
                "displayName": "Brock Bowers",
                "canonicalName": "Brock Bowers",
                "position": "TE",
                "assetClass": "offense",
                "rankDerivedValue": 9177,
                "canonicalConsensusRank": 6,
                # Top-level raw values — ``ktcSfTep`` is preferred over
                # the meta valueContribution.
                "ktc": 7932,
                "ktcSfTep": 9594,
                "sourceRankMeta": {
                    "ktc": {"valueContribution": 7950},
                    "ktcSfTep": {"valueContribution": 9999},
                    "fp_sf": {"valueContribution": 8500},
                },
                "sourceRanks": {"ktc": 14, "ktcSfTep": 6, "fp_sf": 9},
            }
        ],
    }
    source_history.append_snapshot(contract, date="2026-05-05", path=path)

    # On disk: ``ktc`` is gone from both sources and sourceRanks.
    snap = json.loads(path.read_text().strip().splitlines()[0])
    bowers_entry = next(v for k, v in snap["players"].items() if k.startswith("Brock Bowers"))
    assert "ktc" not in bowers_entry["sources"]
    assert "ktc" not in bowers_entry.get("sourceRanks", {})
    # ``ktcSfTep`` is the raw scrape value, not the Hill contribution.
    assert bowers_entry["sources"]["ktcSfTep"] == 9594

    # Read-time: ``load_player_history`` confirms the chart side too.
    hist = source_history.load_player_history("Brock Bowers", path=path)
    assert "ktc" not in hist["sources"]
    assert hist["sources"]["ktcSfTep"][0]["value"] == 9594


def test_retired_ktc_masked_from_legacy_snapshot_at_read_time(path):
    """Snapshots written *before* the write-time filter landed still
    have ``ktc`` entries on disk.  The read-time filter masks them so
    the chart deduplicates immediately, without rewriting the JSONL.
    """
    legacy = {
        "date": "2026-04-27",
        "players": {
            "Brock Bowers::offense": {
                "blended": 9089,
                "blendedRank": 7,
                "sources": {"ktc": 7943, "ktcSfTep": 10110, "fp_sf": 8500},
                "sourceRanks": {"ktc": 13, "ktcSfTep": 7, "fp_sf": 9},
            }
        },
    }
    path.write_text(json.dumps(legacy) + "\n")
    hist = source_history.load_player_history("Brock Bowers", path=path)
    assert "ktc" not in hist["sources"]
    assert "ktc" not in hist["sourceRanks"]
    # ``ktcSfTep`` and other sources unaffected.
    assert hist["sources"]["ktcSfTep"][0]["value"] == 10110
    assert hist["sources"]["fp_sf"][0]["value"] == 8500


def test_ktc_sftep_uses_raw_top_level_value_over_contribution(path):
    """``ktcSfTep`` is in ``_RAW_VALUE_PREFERRED_KEYS`` because KTC
    publishes a public 0-9999 dynasty board on keeptradecut.com — users
    compare popup values to the website directly.  The per-player
    chart records the raw scrape (``row['ktcSfTep']``) rather than
    the Hill-curve contribution, even when both are available.
    """
    contract = {
        "date": "2026-05-05",
        "playersArray": [
            {
                "displayName": "Bijan Robinson",
                "canonicalName": "Bijan Robinson",
                "position": "RB",
                "assetClass": "offense",
                "rankDerivedValue": 9998,
                "canonicalConsensusRank": 2,
                "ktcSfTep": 9998,  # raw scrape — matches KTC.com
                "sourceRankMeta": {
                    "ktcSfTep": {"valueContribution": 9999},  # Hill contribution
                },
            }
        ],
    }
    source_history.append_snapshot(contract, date="2026-05-05", path=path)
    hist = source_history.load_player_history("Bijan Robinson", path=path)
    # Raw 9998 wins, not the contribution 9999.
    assert hist["sources"]["ktcSfTep"][0]["value"] == 9998


def test_ktc_sftep_reads_raw_from_rawsource_values_field(path):
    """Production ``playersArray`` rows from ``_derive_player_row``
    stamp the raw scrape under ``row['rawSourceValues']['ktcSfTep']``,
    NOT at the top level.  This is the path the live snapshot writer
    takes — verify the extractor reads it correctly so today's
    snapshot reflects KTC.com's published value, not the Hill-curve
    contribution.

    Regression guard: between PR #395 and the follow-up, the writer
    was checking top-level ``row['ktcSfTep']`` (a key never set by the
    contract builder), so live snapshots were silently falling
    through to the meta loop and recording valueContribution.
    """
    # Contract row matches what _derive_player_row actually emits: no
    # top-level ktcSfTep; raw lives only under rawSourceValues.
    contract = {
        "date": "2026-05-05",
        "playersArray": [
            {
                "displayName": "Colston Loveland",
                "canonicalName": "Colston Loveland",
                "position": "TE",
                "assetClass": "offense",
                "rankDerivedValue": 7527,
                "canonicalConsensusRank": 23,
                "canonicalSiteValues": {"ktcSfTep": 8434},  # synthetic divergent value
                "rawSourceValues": {"ktcSfTep": 7334},  # raw scrape
                "sourceRankMeta": {
                    "ktcSfTep": {"valueContribution": 7648},  # Hill contribution
                },
            }
        ],
    }
    source_history.append_snapshot(contract, date="2026-05-05", path=path)
    hist = source_history.load_player_history("Colston Loveland", path=path)
    # The raw scrape (7334) wins — not the contribution (7648) or the
    # canonicalSites value (8434).  Post PR #406 the canonicalSites
    # entry equals the raw scrape in production; this fixture uses
    # divergent values to prove the priority order is enforced.
    assert hist["sources"]["ktcSfTep"][0]["value"] == 7334


def test_ktc_sftep_falls_back_to_contribution_when_raw_missing(path):
    """If a contract row is missing the top-level ``ktcSfTep`` raw
    value (e.g. legacy export, partial scrape), fall back to the
    ``valueContribution`` so the chart isn't blank.
    """
    contract = {
        "date": "2026-05-05",
        "playersArray": [
            {
                "displayName": "Some Player",
                "canonicalName": "Some Player",
                "position": "WR",
                "assetClass": "offense",
                "rankDerivedValue": 7000,
                # No top-level ``ktcSfTep`` — only the meta entry.
                "sourceRankMeta": {
                    "ktcSfTep": {"valueContribution": 7100},
                },
            }
        ],
    }
    source_history.append_snapshot(contract, date="2026-05-05", path=path)
    hist = source_history.load_player_history("Some Player", path=path)
    assert hist["sources"]["ktcSfTep"][0]["value"] == 7100


def test_idp_show_ranks_written_and_read_for_idp_player(path):
    """Regression guard for the IDP Show rank round-trip.

    The live contract builder stamps ``sourceRanks["idpShow"]`` on IDP
    player rows (the shared-market-translated effective rank, e.g. 40
    for the #1 IDP player).  This test simulates two consecutive daily
    scrape snapshots — the minimum needed for the rank chart to render
    a line — and confirms:

    1. ``append_snapshot`` writes ``sourceRanks["idpShow"]`` into the
       JSONL when the contract row carries it.
    2. ``load_player_history`` returns ``sourceRanks["idpShow"]`` with
       two data points so the chart line can be drawn.
    3. The scope filter does NOT drop ``idpShow`` for an IDP-class player
       (it would be wrong to drop it — ``idpShow`` has scope=overall_idp
       which legitimately covers the "idp" asset class).
    """

    def _idp_contract(date, rank):
        return {
            "date": date,
            "playersArray": [
                {
                    "displayName": "Travis Hunter",
                    "canonicalName": "Travis Hunter",
                    "position": "CB",
                    "assetClass": "idp",
                    "rankDerivedValue": 5800,
                    "canonicalConsensusRank": rank,
                    # Simulates what the contract builder stamps after Phase 1
                    # (idpShow effective rank = shared-market translated rank)
                    # and Phase 3 (valueContribution from the Hill curve).
                    "sourceRanks": {
                        "idpShow": 40,
                        "fantasyProsIdp": 38,
                        "idpTradeCalc": 42,
                    },
                    "sourceRankMeta": {
                        "idpShow": {"valueContribution": 5800},
                        "fantasyProsIdp": {"valueContribution": 6100},
                        "idpTradeCalc": {"valueContribution": 5500},
                    },
                }
            ],
        }

    source_history.append_snapshot(_idp_contract("2026-05-01", 40), date="2026-05-01", path=path)
    source_history.append_snapshot(_idp_contract("2026-05-02", 41), date="2026-05-02", path=path)

    hist = source_history.load_player_history("Travis Hunter", asset_class="idp", path=path)

    # Values appear for idpShow (the Hill-curve contribution).
    assert "idpShow" in hist["sources"], "idpShow must be in value history"
    assert len(hist["sources"]["idpShow"]) == 2

    # Ranks also appear — the chart requires 2+ data points to draw a line.
    assert "idpShow" in hist["sourceRanks"], "idpShow must be in rank history"
    assert len(hist["sourceRanks"]["idpShow"]) == 2
    assert hist["sourceRanks"]["idpShow"][0]["rank"] == 40
    assert hist["sourceRanks"]["idpShow"][1]["rank"] == 40

    # Blended rank appears too — needed for the "Our rank" line on the chart.
    blended_ranks = [p["rank"] for p in hist["blended"] if p["rank"] is not None]
    assert len(blended_ranks) == 2, "blended rank must accumulate for rank chart to render"
