"""Batch G — as-of replay of a stored generation (``replay.py``).

Pins (``docs/draft/DRAFT_VALUATION_WORKSTREAM.md`` → Batch G):

* every repo-tracked published allocation (2027 / 2028 / 2029) replays, as of
  its own effective time and later, BYTE FOR BYTE from the stored ledger and
  its receipts;
* no future input is selectable: a completed class observed after ``as_of``,
  a record effective after ``as_of``, rookie inputs effective after the
  record, and a promotion pointer written after ``as_of`` are all excluded —
  while the same inputs ARE selected once ``as_of`` passes them;
* an honest refusal or a named difference, never a guess.

All writes go to ``tmp_path`` copies; nothing under ``config/`` is touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.draft.rookie_auction import published
from src.draft.rookie_auction.generation import class_curve_candidate
from src.draft.rookie_auction.ledger import finalize_completed_class
from src.draft.rookie_auction.replay import (
    PROVENANCE_RECOMPUTED,
    PROVENANCE_VERIFIED_RECEIPTS,
    STATE_DIFFERS,
    STATE_REFUSED,
    STATE_REPRODUCED,
    STATE_UNAVAILABLE,
    replay_generation,
)
from src.draft.rookie_auction.snapshots import CONFIG_DIR, canonical_checksum, select_spine_years
from tests.draft_valuation.test_rollover_ledger import CUTOFF, DONE_AT, _evidence, _inputs

LEAGUE = "dynasty_main"
REPO = Path(__file__).resolve().parents[2]
NOW = "2026-10-18T12:00:00+00:00"
SEEDS = {
    2027: ("20261017T000000Z__6da3147efff615db.json", PROVENANCE_VERIFIED_RECEIPTS),
    2028: ("20261018T000000Z__559a3dde5b6f6f5c.json", PROVENANCE_RECOMPUTED),
    2029: ("20261018T000000Z__96d73a274166be90.json", PROVENANCE_RECOMPUTED),
}


@pytest.fixture()
def world(tmp_path):
    """A private copy of the ledger + store, and an empty promotion root."""
    cfg = tmp_path / "draft_valuation"
    shutil.copytree(CONFIG_DIR, cfg)
    return {
        "cfg": cfg,
        "store": cfg / "published_allocations",
        "root": tmp_path / "promotion_root",
    }


def _replay(world, year, as_of):
    return replay_generation(
        LEAGUE,
        year,
        as_of,
        config_dir=world["cfg"],
        store_dirs=[world["store"]],
        promotion_root=world["root"],
    )


def _seed(year):
    return json.loads(
        (published.REPO_STORE / LEAGUE / str(year) / SEEDS[year][0]).read_text("utf-8")
    )


def _file_record(world, year, record):
    d = world["store"] / LEAGUE / str(year)
    stamp = published._ts(record["effectiveAt"]).strftime("%Y%m%dT%H%M%SZ")
    record["checksum"] = {"algorithm": "sha256", "value": canonical_checksum(record)}
    path = d / f"{stamp}__{record['checksum']['value'][:16]}.json"
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return path


# --- byte-for-byte reproduction of the tracked records ------------------------------------


@pytest.mark.parametrize("year", sorted(SEEDS))
def test_every_tracked_record_replays_byte_for_byte(world, year):
    seed = _seed(year)
    for as_of in (seed["effectiveAt"], NOW):
        out = _replay(world, year, as_of)
        assert out.state == STATE_REPRODUCED, out.to_dict()
        assert out.reproduced and out.reasons == ("byte_identical",)
        assert Path(out.stored_path).name == SEEDS[year][0]
        assert out.stored_checksum == out.replayed_checksum == seed["checksum"]["value"]
        assert out.provenance_mode == SEEDS[year][1]
        assert out.spine_years == (2024, 2025, 2026)
    # The replay reads the repo store as data and writes nothing there.
    assert sorted(p.name for p in (world["store"] / LEAGUE / str(year)).iterdir()) == [
        SEEDS[year][0]
    ]


def test_the_default_stores_replay_too_and_stay_untouched():
    before = sorted(p.name for p in published.REPO_STORE.rglob("*.json"))
    for year in SEEDS:
        assert replay_generation(LEAGUE, year, NOW).reproduced
    assert sorted(p.name for p in published.REPO_STORE.rglob("*.json")) == before


def test_before_any_record_is_unavailable_never_a_later_record(world):
    out = _replay(world, 2028, "2026-10-17T23:59:59+00:00")
    assert out.state == STATE_UNAVAILABLE and out.reasons == ("no_record_effective_as_of",)
    assert out.excluded_future_records == (SEEDS[2028][0],)
    assert out.stored_path is None


# --- no future input is selectable ---------------------------------------------------------


def _finalize_2027(world):
    finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=world["cfg"],
    )


def test_a_class_completed_after_as_of_is_not_in_the_spine(world):
    _finalize_2027(world)  # completion observed 2027-05-20
    # The ledger as it stands now WOULD put 2027 in 2028's spine ...
    assert select_spine_years(2028, league_key=LEAGUE, config_dir=world["cfg"]) == (
        2025,
        2026,
        2027,
    )
    # ... but as of 2026-10-18 it did not exist, and the replay never selects it.
    out = _replay(world, 2028, NOW)
    assert out.state == STATE_REPRODUCED, out.to_dict()
    assert out.spine_years == (2024, 2025, 2026)
    row = next(r for r in out.ledger if r["draftClass"] == 2027)
    assert row["usableAsOf"] is False and row["completionObservedAt"] == DONE_AT


def _publish_later_2028(world, at="2027-06-01T00:00:00+00:00"):
    cand = class_curve_candidate(LEAGUE, 2028, now=at, config_dir=world["cfg"])
    assert isinstance(cand, published.AllocationCandidate), cand
    alloc = published.resolve_published_allocation(
        LEAGUE, 2028, candidate=cand, store_dirs=[world["store"]], write_dir=world["store"]
    )
    assert alloc.allocation_state == "current" and alloc.effective_at == at
    return alloc


def test_a_record_effective_after_as_of_is_not_selectable(world):
    _finalize_2027(world)
    later = _publish_later_2028(world)
    seed = _seed(2028)
    assert later.record_checksum != seed["checksum"]["value"]
    assert later.final_whole_dollars != tuple(r["dollars"] for r in seed["finalWholeDollars"])

    # As of 2026-10-18 the seed is in force; the 2027-06-01 record is excluded.
    old = _replay(world, 2028, NOW)
    assert old.state == STATE_REPRODUCED and old.stored_checksum == seed["checksum"]["value"]
    assert len(old.excluded_future_records) == 1
    assert old.excluded_future_records[0].startswith("20270601T000000Z__")

    # Once as_of passes it, the later record is selected and replays byte for byte
    # on the spine that existed then (2027 completed on 2027-05-20).
    new = _replay(world, 2028, "2027-06-02T00:00:00+00:00")
    assert new.state == STATE_REPRODUCED, new.to_dict()
    assert new.stored_checksum == later.record_checksum
    assert new.spine_years == (2025, 2026, 2027) and new.excluded_future_records == ()


def test_record_in_force_on_a_spine_that_has_since_rolled_is_named_not_hidden(world):
    _finalize_2027(world)
    # Between 2027's completion and the next 2028 record, the record in force was
    # built on 2024-2026 while the as-of spine is 2025-2027: a named difference.
    out = _replay(world, 2028, "2027-05-25T00:00:00+00:00")
    assert out.state == STATE_DIFFERS
    assert out.reasons == ("spine_differs:record=[2024, 2025, 2026]:as_of=[2025, 2026, 2027]",)


def test_inputs_effective_after_the_record_are_refused(world):
    record = _seed(2028)
    record = {k: v for k, v in record.items() if k != "checksum"}
    record["effectiveAt"] = "2026-10-16T12:00:00+00:00"  # before the 2026-10-17 baseline
    _file_record(world, 2028, record)
    out = _replay(world, 2028, "2026-10-16T18:00:00+00:00")
    assert out.state == STATE_REFUSED
    assert out.reasons == ("inputs_not_effective_as_of:2026-10-17",)


def test_a_pointer_after_as_of_is_ignored_one_before_is_refused(world):
    _finalize_2027(world)
    cand = class_curve_candidate(
        LEAGUE, 2028, now="2027-06-01T00:00:00+00:00", config_dir=world["cfg"]
    )
    published.publish_promoted_generation(
        LEAGUE, cand, at="2027-06-01T00:00:00+00:00", reason="test", root=world["root"]
    )
    before = _replay(world, 2028, NOW)
    assert before.state == STATE_REPRODUCED and before.ignored_future_pointers == (1,)
    after = _replay(world, 2028, "2027-06-02T00:00:00+00:00")
    assert after.state == STATE_REFUSED
    assert after.reasons == ("promoted_generation_replay_not_supported",)


# --- honest refusals and named differences --------------------------------------------------


def test_receipt_mismatch_is_a_named_difference(world):
    record = {k: v for k, v in _seed(2029).items() if k != "checksum"}
    record["provenance"] = {**record["provenance"], "frozenInputsChecksum": "0" * 64}
    record["effectiveAt"] = "2026-10-18T06:00:00+00:00"
    _file_record(world, 2029, record)
    out = _replay(world, 2029, NOW)
    assert out.state == STATE_DIFFERS and out.reasons == ("frozen_inputs_checksum_differs",)


def test_edited_record_bytes_are_never_replayed(world):
    path = world["store"] / LEAGUE / "2029" / SEEDS[2029][0]
    path.write_text(path.read_text("utf-8").replace('"dollars": 135', '"dollars": 136', 1), "utf-8")
    out = _replay(world, 2029, NOW)
    assert out.state == STATE_UNAVAILABLE and out.reasons == ("no_record_effective_as_of",)


@pytest.mark.parametrize(
    ("league", "as_of", "reason"),
    [
        ("dynasty_new", NOW, "league_not_configured:dynasty_new"),
        (LEAGUE, "2026-10-18T12:00:00", "as_of_unreadable:"),
        (LEAGUE, "not a time", "as_of_unreadable:"),
    ],
)
def test_refusals(world, league, as_of, reason):
    out = replay_generation(
        league, 2028, as_of, store_dirs=[world["store"]], promotion_root=world["root"]
    )
    assert out.state == STATE_REFUSED and out.reasons[0].startswith(reason)


def test_cli_exit_codes():
    script = REPO / "scripts" / "draft_valuation_replay.py"
    ok = subprocess.run(
        [sys.executable, str(script), "--year", "2028", "--as-of", NOW],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["state"] == STATE_REPRODUCED
    early = subprocess.run(
        [sys.executable, str(script), "--year", "2028", "--as-of", "2026-10-01T00:00:00+00:00"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert early.returncode == 3 and json.loads(early.stdout)["state"] == STATE_UNAVAILABLE
