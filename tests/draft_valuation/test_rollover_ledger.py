"""Batch C — completed-class rollover ledger (dynasty_main only)."""

from __future__ import annotations

import json
import os
import shutil
import threading
from decimal import Decimal

import pytest

from src.draft.rookie_auction import ledger as ledger_mod
from src.draft.rookie_auction.class_snapshot import build_class_candidate, frozen_fallback_snapshot
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError
from src.draft.rookie_auction.ledger import (
    ImmutableSnapshotConflict,
    LedgerRefusal,
    finalize_completed_class,
    replay_spine,
)
from src.draft.rookie_auction.snapshots import (
    CONFIG_DIR,
    SnapshotIntegrityError,
    available_completed_classes,
    canonical_checksum,
    load_completed_class_curve,
    select_spine_years,
)
from src.identity.pick_lifecycle import DraftObservation, LeagueDraftEvidence

LEAGUE = "dynasty_main"
PRE_DRAFT = "2027-04-20T00:00:00+00:00"
CUTOFF = "2027-05-01T00:00:00+00:00"
DONE_AT = "2027-05-20T12:00:00+00:00"


@pytest.fixture()
def cfg(tmp_path):
    dst = tmp_path / "draft_valuation"
    shutil.copytree(CONFIG_DIR, dst)
    return dst


def _evidence(season=2027, *, status="complete", rostered=70, league=LEAGUE, observed=DONE_AT):
    return LeagueDraftEvidence(
        league_key=league,
        sleeper_league_id="sleeper-123",
        observed_at=observed,
        drafts=(
            DraftObservation(
                draft_id=f"d{season}",
                season=season,
                status=status,
                player_type=1,
                pick_count=72,
                rookie_pick_count=72,
                rostered_pick_count=rostered,
            ),
        ),
    )


def _inputs(season=2027, *, as_of=PRE_DRAFT, n=72, start=9000):
    rows = [
        {
            "playerId": f"r{season}-{i:03d}",
            "canonicalName": f"Rookie {season}-{i}",
            "position": "LB" if i % 6 == 0 else "WR",
            "assetClass": "idp" if i % 6 == 0 else "offense",
            "eligibleDraftYear": season,
            "rankDerivedValue": start - 41 * i,
        }
        for i in range(n)
    ]
    return build_class_candidate(
        {"playersArray": rows},
        target_draft_year=season,
        league_key=LEAGUE,
        observed_nfl_season=None,
        as_of=as_of,
    )


def test_spine_rolls_only_when_a_completed_class_is_filed(cfg):
    assert select_spine_years(2027, league_key=LEAGUE, config_dir=cfg) == (2024, 2025, 2026)
    with pytest.raises(LookupError):
        select_spine_years(2028, [2024, 2025], league_key=LEAGUE)
    # Before 2027 completes, 2028's spine is still 2024-2026: nothing is invented.
    assert select_spine_years(2028, league_key=LEAGUE, config_dir=cfg) == (2024, 2025, 2026)

    out = finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    assert out.created and out.spine_years == (2024, 2025, 2026)
    assert select_spine_years(2028, league_key=LEAGUE, config_dir=cfg) == (2025, 2026, 2027)
    # 2024 left the window but stays readable for replay.
    assert load_completed_class_curve(2024, league_key=LEAGUE, config_dir=cfg).dollars
    assert available_completed_classes(league_key=LEAGUE, config_dir=cfg) == (
        2024,
        2025,
        2026,
        2027,
    )

    curve = load_completed_class_curve(2027, league_key=LEAGUE, config_dir=cfg)
    assert sum(curve.dollars) == Decimal(1200) and curve.kind == "generated_class_curve"
    assert curve.completion_observed_at == DONE_AT

    # And the next roll: 2028 filed on its own completion -> 2029 uses 2026-2028.
    finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2028,
        inputs=_inputs(2028, as_of="2028-04-20T00:00:00+00:00"),
        evidence=_evidence(2028, observed="2028-05-20T00:00:00+00:00"),
        pre_draft_cutoff="2028-05-01T00:00:00+00:00",
        config_dir=cfg,
    )
    assert select_spine_years(2029, league_key=LEAGUE, config_dir=cfg) == (2026, 2027, 2028)


def test_snapshot_records_the_full_provenance(cfg):
    out = finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    p = json.loads(out.path.read_text("utf-8"))
    assert p["checksum"]["value"] == canonical_checksum(p) == out.checksum
    assert p["spineYears"] == [2024, 2025, 2026] and set(p["spineChecksums"]) == {
        "2024",
        "2025",
        "2026",
    }
    assert p["formulaVersion"] == "draft_data_workbook_v1"
    assert p["leagueConfig"] == {
        "teamCount": 12,
        "rounds": 6,
        "budgetDollars": 1200,
        "unitsPerDollar": 2,
    }
    assert p["draftCompletion"]["status"] == "retired" and p["createdAt"] == DONE_AT
    assert (
        p["provenance"]["preDraftCutoff"] == CUTOFF and p["provenance"]["inputsAsOf"] == PRE_DRAFT
    )
    assert p["validation"]["totalDollars"] == "1200" and len(p["dollars"]) == 72
    whole = [row["dollars"] for row in p["finalWholeDollars"]]
    assert sum(whole) == 1200 and all(isinstance(d, int) for d in whole)
    assert p["validation"]["wholeDollars"]["finalWholeDollars"] == whole


def test_identical_evidence_is_idempotent(cfg):
    kwargs = dict(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    first = finalize_completed_class(**kwargs)
    second = finalize_completed_class(**kwargs)
    assert first.created and not second.created and first.checksum == second.checksum
    assert len(list((cfg / "historical_curves" / LEAGUE).glob("*.tmp"))) == 0


def test_changed_source_after_finalization_cannot_rewrite_history(cfg):
    finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    before = (cfg / "historical_curves" / LEAGUE / "2027.json").read_bytes()
    with pytest.raises(ImmutableSnapshotConflict):
        finalize_completed_class(
            league_key=LEAGUE,
            draft_class=2027,
            inputs=_inputs(start=8000),
            evidence=_evidence(),
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    assert (cfg / "historical_curves" / LEAGUE / "2027.json").read_bytes() == before


def test_two_simultaneous_jobs_file_one_snapshot(cfg):
    results, errors = [], []

    def run():
        try:
            results.append(
                finalize_completed_class(
                    league_key=LEAGUE,
                    draft_class=2027,
                    inputs=_inputs(),
                    evidence=_evidence(),
                    pre_draft_cutoff=CUTOFF,
                    config_dir=cfg,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sum(1 for r in results if r.created) == 1
    assert len({r.checksum for r in results}) == 1


@pytest.mark.parametrize(
    "evidence,reason",
    [
        (_evidence(status="drafting"), "class_not_verified_complete"),
        (_evidence(status="pre_draft"), "class_not_verified_complete"),
        (_evidence(rostered=10), "class_not_verified_complete"),  # complete, not rostered
        (_evidence(rostered=None), "class_not_verified_complete"),  # rosters unobserved
        (_evidence(season=2026), "class_not_verified_complete"),  # wrong season's draft
        (_evidence(league="other_league"), "evidence_league_mismatch"),
    ],
)
def test_unverified_completion_is_refused(cfg, evidence, reason):
    with pytest.raises(LedgerRefusal) as exc:
        finalize_completed_class(
            league_key=LEAGUE,
            draft_class=2027,
            inputs=_inputs(),
            evidence=evidence,
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    assert exc.value.reason == reason
    assert not (cfg / "historical_curves" / LEAGUE / "2027.json").exists()


def test_post_draft_inputs_are_never_filed_as_pre_draft(cfg):
    with pytest.raises(LedgerRefusal) as exc:
        finalize_completed_class(
            league_key=LEAGUE,
            draft_class=2027,
            inputs=_inputs(as_of="2027-05-15T00:00:00+00:00"),
            evidence=_evidence(),
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    assert exc.value.reason == "inputs_after_pre_draft_cutoff"
    with pytest.raises(LedgerRefusal) as exc:
        finalize_completed_class(
            league_key=LEAGUE,
            draft_class=2027,
            inputs=_inputs(),
            evidence=_evidence(observed="2027-04-25T00:00:00+00:00"),
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    assert exc.value.reason == "cutoff_after_completion_observation"
    with pytest.raises(LedgerRefusal) as exc:
        finalize_completed_class(
            league_key=LEAGUE,
            draft_class=2027,
            inputs=_inputs(as_of=None),
            evidence=_evidence(),
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    assert exc.value.reason == "timestamp_missing"


def test_incomplete_or_mismatched_inputs_are_refused(cfg):
    for inputs, reason in (
        (_inputs(n=50), "inputs_incomplete"),
        (_inputs(2028, as_of="2027-04-01T00:00:00+00:00"), "inputs_for_another_class_or_league"),
    ):
        with pytest.raises(LedgerRefusal) as exc:
            finalize_completed_class(
                league_key=LEAGUE,
                draft_class=2027,
                inputs=inputs,
                evidence=_evidence(),
                pre_draft_cutoff=CUTOFF,
                config_dir=cfg,
            )
        assert exc.value.reason == reason


def test_frozen_template_can_be_filed_with_its_own_provenance(cfg):
    """If 2027 completes before its real inputs qualify, the curve that priced
    it (frozen template) is what gets filed — labelled as such."""
    frozen = frozen_fallback_snapshot(2027, league_key=LEAGUE)
    frozen = type(frozen)(**{**frozen.__dict__, "as_of": "2026-10-17T00:00:00+00:00"})
    out = finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=frozen,
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    p = json.loads(out.path.read_text("utf-8"))
    assert p["provenance"]["inputsMode"] == "frozen_fallback"
    assert p["provenance"]["actualInputClassYear"] == 2026


def test_failed_write_leaves_nothing_behind(cfg, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(ledger_mod.os, "link", boom)
    with pytest.raises(OSError):
        finalize_completed_class(
            league_key=LEAGUE,
            draft_class=2027,
            inputs=_inputs(),
            evidence=_evidence(),
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    d = cfg / "historical_curves" / LEAGUE
    assert sorted(p.name for p in d.iterdir()) == ["2024.json", "2025.json", "2026.json"]


def test_generated_snapshot_without_verified_completion_is_unloadable(cfg):
    out = finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    p = json.loads(out.path.read_text("utf-8"))
    p["draftCompletion"]["status"] = "unknown"
    p["checksum"]["value"] = canonical_checksum(p)
    os.chmod(out.path, 0o644)
    out.path.write_text(json.dumps(p), "utf-8")
    with pytest.raises(SnapshotIntegrityError, match="completion"):
        load_completed_class_curve(2027, league_key=LEAGUE, config_dir=cfg)


def test_replay_as_of(cfg):
    finalize_completed_class(
        league_key=LEAGUE,
        draft_class=2027,
        inputs=_inputs(),
        evidence=_evidence(),
        pre_draft_cutoff=CUTOFF,
        config_dir=cfg,
    )
    before = replay_spine(
        2028, league_key=LEAGUE, as_of="2027-05-01T00:00:00+00:00", config_dir=cfg
    )
    after = replay_spine(2028, league_key=LEAGUE, as_of="2027-06-01T00:00:00+00:00", config_dir=cfg)
    now = replay_spine(2028, league_key=LEAGUE, config_dir=cfg)
    assert before["spineYears"] == [2024, 2025, 2026]
    assert after["spineYears"] == now["spineYears"] == [2025, 2026, 2027]
    flags = {r["draftClass"]: r["asOfUnknown"] for r in now["ledger"]}
    assert flags == {2024: True, 2025: True, 2026: True, 2027: False}
    assert replay_spine(2026, league_key=LEAGUE, config_dir=cfg)["spineYears"] is None


@pytest.mark.parametrize("league", ["dynasty_new", "other"])
def test_ledger_refuses_unconfigured_leagues(cfg, league):
    with pytest.raises(LeagueNotConfiguredError):
        finalize_completed_class(
            league_key=league,
            draft_class=2027,
            inputs=_inputs(),
            evidence=_evidence(league=league),
            pre_draft_cutoff=CUTOFF,
            config_dir=cfg,
        )
    with pytest.raises(LeagueNotConfiguredError):
        replay_spine(2027, league_key=league, config_dir=cfg)
