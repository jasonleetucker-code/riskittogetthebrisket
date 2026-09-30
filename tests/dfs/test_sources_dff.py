"""Daily Fantasy Fuel adapter: parse, salary-confirmed join, cached fetch, honest failures.

No real page is committed: the fixture is SYNTHETIC, generated in the page's
row shape from the repo's synthetic DraftKings slate.
"""

from __future__ import annotations

import io
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.dfs import pit, sources_dff, store
from src.dfs.imports import parse_draftkings_salaries

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def _athletes():
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    return athletes


def _page(athletes, *, salary_off=None):
    rows = []
    for i, a in enumerate(athletes):
        salary = a.salary + 100 if a.player_id == salary_off else a.salary
        rows.append(
            f'<tr class=" projections-listing " data-start_date="2026-10-04" data-name="{a.name}" '
            f'data-pos="{a.positions[0]}" data-team="{a.team}" data-opp="{a.opponent or ""}" '
            f'data-spread="-3.5" data-ou= "47.5" data-proj_score="25" data-salary="{salary}" '
            f'data-ppg_proj="{10 + i % 9}.5" data-szn_avg="12.0" data-player_id="X{i}" >'
        )
    return "<html><table>" + "".join(rows) + "</table></html>"


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _snapshot(athletes):
    meta = store.put_snapshot(
        "o",
        "draftkings.nfl.classic@2026.1",
        "h" * 64,
        {"athletes": [a.to_dict() for a in athletes]},
    )
    return store.get_snapshot("o", meta["id"])


def test_parse_reads_the_documented_row_attributes():
    rows = sources_dff.parse(_page(_athletes()[:2]))
    assert (
        rows[0]["overUnder"] == 47.5
        and rows[0]["impliedTeamTotal"] == 25.0
        and rows[0]["projection"] == 10.5
    )
    assert sources_dff.parse("<html>nothing here</html>") == []


def test_pull_joins_by_name_team_position_confirmed_by_salary_and_records_at_fetch_time(
    monkeypatch,
):
    athletes = _athletes()
    snap = _snapshot(athletes)
    page = _page(athletes, salary_off=athletes[3].player_id).encode()
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        assert "ChaseUpside" in req.headers["User-agent"] and timeout == sources_dff.TIMEOUT_S
        return _Resp(page)

    monkeypatch.setattr(sources_dff.urllib.request, "urlopen", fake_urlopen)
    out = sources_dff.pull("o", snap, "nfl", "draftkings", athletes)
    assert out["matched"] == len(athletes) - 1  # the salary-mismatched row is quarantined
    assert out["quarantined"][0]["reason"] == "no_slate_athlete_or_salary_mismatch"
    assert out["observations"]["added"] == 2 * (len(athletes) - 1)  # projection + context each
    view = pit.as_of("o", snap["id"], datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc))
    held = view["players"][athletes[0].player_id]
    assert held["projection"]["dailyfantasyfuel"]["value"] == 10.5
    assert held["context"]["dailyfantasyfuel"]["value"]["impliedTeamTotal"] == 25.0
    # A second pull inside the refetch window is served from cache: one network call total.
    again = sources_dff.pull("o", snap, "nfl", "draftkings", athletes)
    assert again["fromCache"] is True and calls == [
        "https://www.dailyfantasyfuel.com/nfl/projections/draftkings"
    ]


def test_failures_are_named_not_hidden(monkeypatch):
    athletes = _athletes()
    snap = _snapshot(athletes)

    def down(req, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(sources_dff.urllib.request, "urlopen", down)
    with pytest.raises(sources_dff.SourceError) as exc:
        sources_dff.pull("o", snap, "nfl", "draftkings", athletes)
    assert exc.value.code == "PROVIDER_UNAVAILABLE"
    monkeypatch.setattr(
        sources_dff.urllib.request, "urlopen", lambda req, timeout: _Resp(b"<html></html>")
    )
    with pytest.raises(sources_dff.SourceError) as exc:
        sources_dff.pull("o", snap, "nfl", "draftkings", athletes)
    assert exc.value.code == "SOURCE_EMPTY"
    with pytest.raises(sources_dff.SourceError) as exc:
        sources_dff.fetch("mma", "draftkings")
    assert exc.value.code == "UNSUPPORTED_SOURCE_SLATE"
