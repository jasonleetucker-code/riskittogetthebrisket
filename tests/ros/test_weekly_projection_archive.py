"""Weekly projection archive (RET evidence) + its collector script — no network."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ros import weekly_league_projections as wlp
from src.ros import weekly_projection_archive as arc
from src.ros.fptrack_weekly_projections import FPTrackFetchResult
from src.ros.sleeper_weekly_projections import FetchResult

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "weekly_projections"
T0 = datetime(2026, 10, 27, 14, 10, tzinfo=timezone.utc)


def _rows() -> list[dict]:
    return json.loads((FIX / "sleeper_week8_sample.json").read_text(encoding="utf-8"))


def test_write_then_identical_recapture_is_a_noop(tmp_path):
    first = arc.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=8,
        fetched_at=T0,
        rows=_rows(),
        base_dir=tmp_path,
    )
    assert first.status == "written" and first.path.exists()
    again = arc.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=8,
        fetched_at=T0 + timedelta(hours=2),
        rows=_rows(),
        base_dir=tmp_path,
    )
    assert again.status == "unchanged" and again.path == first.path
    assert len(arc.list_captures(2026, 8, base_dir=tmp_path)) == 1


def test_changed_content_appends_a_new_file_and_keeps_the_old(tmp_path):
    arc.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=8,
        fetched_at=T0,
        rows=_rows(),
        base_dir=tmp_path,
    )
    changed = _rows()
    changed[0]["stats"]["idp_tkl_solo"] = 9.9
    second = arc.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=8,
        fetched_at=T0 + timedelta(days=2),
        rows=changed,
        base_dir=tmp_path,
    )
    caps = arc.list_captures(2026, 8, source_key="sleeperWeeklyProjections", base_dir=tmp_path)
    assert second.status == "written" and len(caps) == 2
    first_rows = arc.load_capture(caps[0].path)["rows"]
    assert first_rows[0]["stats"]["idp_tkl_solo"] != 9.9  # history is not rewritten


def test_hash_content_ignores_volatile_stamps(tmp_path):
    rows = _rows()
    stable = [{k: v for k, v in r.items() if k != "updated_at"} for r in rows]
    arc.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=8,
        fetched_at=T0,
        rows=rows,
        hash_content=stable,
        base_dir=tmp_path,
    )
    restamped = [dict(r, updated_at=1) for r in rows]
    res = arc.record_capture(
        source_key="sleeperWeeklyProjections",
        season=2026,
        week=8,
        fetched_at=T0 + timedelta(hours=1),
        rows=restamped,
        hash_content=[{k: v for k, v in r.items() if k != "updated_at"} for r in restamped],
        base_dir=tmp_path,
    )
    assert res.status == "unchanged"


def test_capture_record_fields(tmp_path):
    res = arc.record_capture(
        source_key="fptrackWeeklyProjections",
        season=2026,
        week=8,
        fetched_at="2026-10-29T09:05:00Z",
        rows={"players": [{"a": 1}]},
        provider_updated_at=["2026-10-29T08:00:00+00:00", None],
        league_scored={"sf1:x": {"leagueKeys": ["dynasty_main"], "points": {"1": 3.5}}},
        base_dir=tmp_path,
    )
    data = arc.load_capture(res.path)
    assert data["fetchedAt"] == "2026-10-29T09:05:00+00:00"
    assert data["rowCount"] == 1 and data["providerUpdatedAtMax"] == "2026-10-29T08:00:00+00:00"
    assert data["leagueScored"]["sf1:x"]["points"] == {"1": 3.5}
    assert res.path.name.startswith("fptrackWeeklyProjections_20261029T090500")
    assert res.path.parent == tmp_path / "2026" / "w8"


def test_refusals(tmp_path):
    with pytest.raises(arc.WeeklyArchiveError):
        arc.record_capture(
            source_key="x", season=2026, week=8, fetched_at=datetime(2026, 1, 1), rows=[],
            base_dir=tmp_path,
        )  # fmt: skip
    with pytest.raises(arc.WeeklyArchiveError):
        arc.record_capture(
            source_key="bad key", season=2026, week=8, fetched_at=T0, rows=[], base_dir=tmp_path
        )
    with pytest.raises(arc.WeeklyArchiveError):
        arc.check_store_path(REPO / "data" / "ros" / "weekly_archive")


def test_default_archive_root_is_gitignored_and_not_force_added():
    assert "data/ros" not in arc.ARCHIVE_ROOT.as_posix()
    probe = arc.ARCHIVE_ROOT / "2026" / "w8" / "x.json.gz"
    out = subprocess.run(
        ["git", "check-ignore", "-q", str(probe)], cwd=REPO, capture_output=True, check=False
    )
    assert out.returncode == 0, "data/projections/weekly_archive must be gitignored"
    refresh = (REPO / ".github" / "workflows" / "scheduled-refresh.yml").read_text(encoding="utf-8")
    assert "data/projections" not in refresh


# ── collector script ─────────────────────────────────────────────────


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "capture_weekly_projections", REPO / "scripts" / "capture_weekly_projections.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_gate_off_makes_no_call(monkeypatch, capsys):
    from src.api import feature_flags

    mod = _script()
    monkeypatch.delenv("RISKIT_FEATURE_WEEKLY_PROJECTION_CAPTURE", raising=False)
    feature_flags.reload()
    monkeypatch.setattr(mod, "_fetch", lambda *a: pytest.fail("fetched with the gate off"))
    assert mod.main(["--season", "2026", "--week", "8"]) == 0
    assert "feature_disabled" in capsys.readouterr().out


def test_script_captures_current_week_and_skips_unpublished(monkeypatch, tmp_path):
    from src.api import feature_flags

    mod = _script()
    monkeypatch.setenv("RISKIT_FEATURE_WEEKLY_PROJECTION_CAPTURE", "1")
    feature_flags.reload()
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    card = json.loads(
        (REPO / "config" / "league_intel" / "sleeper_league_snapshot_2026-07-26.json").read_text(
            encoding="utf-8"
        )
    )["scoring_settings"]
    monkeypatch.setattr(wlp, "_resolve_scoring", lambda key, s: (card, "fresh", None))

    def fake_fetch(key, season, week):
        if key == wlp.SLEEPER_SOURCE:
            rows = _rows() if week == 8 else []
            return FetchResult(
                "ok", season, week, "u", "2026-10-29T09:05:00+00:00", rows=tuple(rows)
            )
        return FPTrackFetchResult("feature_disabled", season, week, "u", None, reason="off")

    monkeypatch.setattr(mod, "_fetch", fake_fetch)
    try:
        code = mod.main(
            ["--season", "2026", "--week", "8", "--weeks-ahead", "1", "--league-key",
             "dynasty_main", "--base-dir", str(tmp_path)]
        )  # fmt: skip
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_WEEKLY_PROJECTION_CAPTURE")
        feature_flags.reload()
    assert code == 0
    caps = arc.list_captures(2026, 8, base_dir=tmp_path)
    assert [c.source_key for c in caps] == ["sleeperWeeklyProjections"]
    data = arc.load_capture(caps[0].path)
    assert data["rowCount"] == len(_rows())  # the FULL pool, placeholders included
    (fp,) = data["leagueScored"]
    assert data["leagueScored"][fp]["leagueKeys"] == ["dynasty_main"]
    assert "90001" in data["leagueScored"][fp]["points"]
    assert arc.list_captures(2026, 9, base_dir=tmp_path) == []


def test_script_exit_1_when_nothing_usable(monkeypatch, tmp_path):
    from src.api import feature_flags

    mod = _script()
    monkeypatch.setenv("RISKIT_FEATURE_WEEKLY_PROJECTION_CAPTURE", "1")
    feature_flags.reload()
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        mod,
        "_fetch",
        lambda key, s, w: FetchResult("fetch_failed", s, w, "u", None, reason="down"),
    )
    try:
        code = mod.main(
            ["--season", "2026", "--week", "8", "--weeks-ahead", "0", "--league-key",
             "dynasty_main", "--base-dir", str(tmp_path)]
        )  # fmt: skip
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_WEEKLY_PROJECTION_CAPTURE")
        feature_flags.reload()
    assert code == 1
