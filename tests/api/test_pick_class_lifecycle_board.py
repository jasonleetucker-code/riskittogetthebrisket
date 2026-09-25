"""#1414 on the real board: a retired draft class is ABSENT from the
present-tense contract, nothing else about the pick board moves, and an
unproven league keeps the class.

Built from the pinned golden input export (2026-08-04: a 2026 slot class plus
2027/2028 tiers) with the lifecycle evidence supplied the two ways production
supplies it — inside the scrape's sleeper block, and as per-league snapshots
in the scoring-snapshot directory.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from src.api import draft_class_evidence as dce
from src.api import league_registry
from src.api.data_contract import build_api_data_contract, validate_api_data_contract
from src.api.pick_value_resolution import resolve_pick_value
from src.identity.pick_lifecycle import evidence_from_sleeper
from src.identity.picks import MarketPickRef, is_pick_name, pick_year_from_name

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "golden" / "input_export.json.gz"


def _raw() -> dict:
    return json.loads(gzip.open(FIXTURE).read())


def _board_league_id(raw: dict) -> str:
    return str(raw["sleeper"]["leagueId"])


def _retired_evidence(raw: dict, season: int, league_id: str, key: str) -> dict:
    """A completed, fully rostered rookie draft of ``season`` for one league,
    built from the payload's own rostered player ids."""
    rostered = [pid for t in raw["sleeper"]["teams"] for pid in t.get("playerIds") or []][:60]
    picks = [{"player_id": pid, "metadata": {"years_exp": "0"}} for pid in rostered]
    return evidence_from_sleeper(
        league_key=key,
        sleeper_league_id=league_id,
        drafts=[
            {
                "draft_id": f"d{season}",
                "season": str(season),
                "status": "complete",
                "settings": {"player_type": 1},
            },
        ],
        picks_by_draft_id={f"d{season}": picks},
        rostered_player_ids=rostered,
        observed_at="2026-09-24T00:00:00+00:00",
    ).to_dict()


OTHER_LEAGUE_ID = "900000000000000001"


def _write_registry(path: Path, board_lid: str) -> Path:
    """Two active leagues: the one the payload was scraped for, and another
    that may or may not share its scoring.  The suite's conftest points the
    registry at nothing, so this test supplies its own."""
    league = {
        "scoringProfile": "superflex_tep15_ppr1",
        "active": True,
        "rosterSettings": {"teamCount": 12, "rosterSize": 30},
    }
    reg = {
        "schemaVersion": 1,
        "defaultLeagueKey": "board_league",
        "leagues": [
            {**league, "key": "board_league", "displayName": "Board", "sleeperLeagueId": board_lid},
            {
                **league,
                "key": "other_league",
                "displayName": "Other",
                "sleeperLeagueId": OTHER_LEAGUE_ID,
            },
        ],
    }
    target = path / "registry.json"
    target.write_text(json.dumps(reg), encoding="utf-8")
    return target


def _install(mp: pytest.MonkeyPatch, tmp: Path, raw: dict) -> None:
    from src.api import data_contract

    mp.setenv("LEAGUE_REGISTRY_PATH", str(_write_registry(tmp, _board_league_id(raw))))
    mp.setenv("LEAGUE_SCORING_SNAPSHOT_DIR", str(tmp))
    # No live Sleeper fetch from inside a build (conftest's own posture).
    mp.setattr(
        data_contract,
        "_resolve_league_context",
        lambda *a, **k: {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": False},
    )
    league_registry.reload_registry()


def _other_active_leagues(raw: dict) -> list:
    board_lid = _board_league_id(raw)
    return [c for c in league_registry.active_leagues() if c.sleeper_league_id != board_lid]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    raw = _raw()
    _install(monkeypatch, tmp_path, raw)
    yield raw
    monkeypatch.undo()
    league_registry.reload_registry()


def _pick_rows(contract: dict) -> dict[str, dict]:
    return {
        r["canonicalName"]: r for r in contract["playersArray"] if r.get("assetClass") == "pick"
    }


@pytest.fixture(scope="module")
def boards(tmp_path_factory):
    """Two builds of the same payload with the same 2026 evidence for the
    board league.  ``retired``: every other active league's scoring card is
    PROVEN different, so only the board league is consulted.  ``kept``:
    another league's card matches the board's scoring and it has no draft
    evidence, so it is consulted and unknown."""
    raw = _raw()
    board_lid = _board_league_id(raw)
    raw["sleeper"]["draftClassEvidence"] = _retired_evidence(raw, 2026, board_lid, "board_league")

    mp = pytest.MonkeyPatch()
    out = {}
    try:
        different = tmp_path_factory.mktemp("snap_different")
        _install(mp, different, raw)
        others = _other_active_leagues(raw)
        assert others, "the fixture registry carries a second active league"
        for cfg in others:
            card = dict(raw["sleeper"]["scoringSettings"])
            card["rec"] = float(card.get("rec") or 0) + 0.37  # a PROVEN difference
            (different / f"scoring_{cfg.sleeper_league_id}.json").write_text(
                json.dumps({"sleeperLeagueId": cfg.sleeper_league_id, "scoringSettings": card})
            )
        out["retired"] = build_api_data_contract(copy.deepcopy(raw))
        # A LATER class retiring too (2027 evidence; 2026 follows by
        # supersession) — the horizon must still not move.
        later = copy.deepcopy(raw)
        later["sleeper"]["draftClassEvidence"] = _retired_evidence(
            raw, 2027, board_lid, "board_league"
        )
        out["retired_later"] = build_api_data_contract(later)

        same = tmp_path_factory.mktemp("snap_same")
        _install(mp, same, raw)
        for cfg in others:
            (same / f"scoring_{cfg.sleeper_league_id}.json").write_text(
                json.dumps(
                    {
                        "sleeperLeagueId": cfg.sleeper_league_id,
                        "scoringSettings": dict(raw["sleeper"]["scoringSettings"]),
                    }
                )
            )
        out["kept"] = build_api_data_contract(copy.deepcopy(raw))
    finally:
        mp.undo()
        league_registry.reload_registry()
    out["others"] = [c.key for c in others]
    return out


def test_retired_class_is_absent_from_every_present_tense_block(boards):
    c = boards["retired"]
    stamp = c["pickClassLifecycle"]
    assert stamp["retiredYears"] == [2026]
    assert stamp["classes"]["2026"]["status"] == "retired"
    assert stamp["retiredRowCount"] == 90  # 72 slots + 18 tiers in the fixture
    for name in c["players"]:
        if is_pick_name(str(name)):
            assert pick_year_from_name(str(name)) != 2026, name
    assert not [n for n in _pick_rows(c) if n.startswith("2026")]


def test_retired_picks_are_absent_not_zero(boards):
    c = boards["retired"]
    for name, row in _pick_rows(c).items():
        v = row.get("rankDerivedValue")
        assert v is None or v > 0, name
    res = resolve_pick_value(c, MarketPickRef(year=2026, round_num=1, slot=3))
    assert res.value is None and res.reason  # unpriced with a reason — never 0


def test_later_classes_are_untouched(boards):
    kept, retired = _pick_rows(boards["kept"]), _pick_rows(boards["retired"])
    later = [n for n in kept if not n.startswith("2026")]
    assert later, "fixture must carry later classes"
    for name in later:
        assert name in retired, name
        assert retired[name].get("rankDerivedValue") == kept[name].get("rankDerivedValue"), name


def test_retirement_does_not_move_the_future_pick_horizon(boards):
    """Owner decision on #1442: retirement decides which classes are
    present-tense; the horizon stays anchored exactly as before.  Advancing
    it is a separate decision."""
    kept, retired = _pick_rows(boards["kept"]), _pick_rows(boards["retired"])
    assert boards["kept"]["currentDraftYear"] == 2026
    assert boards["retired"]["currentDraftYear"] == 2026
    # The retired board is EXACTLY the kept board minus the 2026 class:
    # nothing added (no 2030 rows), nothing else removed.
    assert set(retired) == {n for n in kept if not n.startswith("2026")}
    assert not any(n.startswith("2030") for n in retired)


def test_a_synthetic_later_retirement_does_not_extend_the_horizon(boards):
    c = boards["retired_later"]
    stamp = c["pickClassLifecycle"]
    assert stamp["retiredYears"] == [2026, 2027]
    assert stamp["classes"]["2026"]["status"] == "retired"  # by supersession
    years = {int(n[:4]) for n in _pick_rows(c)}
    assert years == {2028, 2029}  # no 2030 / 2031 minted to backfill
    assert c["currentDraftYear"] == 2026
    report = validate_api_data_contract(c)
    assert report.get("structuralErrors") == [], report.get("structuralErrors")
    assert not [e for e in report.get("errors") or [] if "pick_count_below_floor" in e]


def test_the_pick_floor_counts_active_classes_only():
    from src.api.data_contract import _pick_count_floor_for_board

    tiers_only = [{"assetClass": "pick", "canonicalName": "2027 Early 1st"}]
    assert _pick_count_floor_for_board(tiers_only) == 77  # 4 classes x 24 x 0.8
    assert (
        _pick_count_floor_for_board(tiers_only, current_year=2026, retired_years=[2026]) == 58
    )  # 3 active classes
    assert (
        _pick_count_floor_for_board(tiers_only, current_year=2026, retired_years=[2026, 2027]) == 39
    )
    # A retired year outside the horizon window discounts nothing.
    assert _pick_count_floor_for_board(tiers_only, current_year=2026, retired_years=[2025]) == 77


def test_retired_board_is_a_valid_contract(boards):
    report = validate_api_data_contract(boards["retired"])
    assert report.get("structuralErrors") == [], report.get("structuralErrors")


def test_an_unproven_served_league_keeps_the_class(boards):
    c = boards["kept"]
    assert c["pickClassLifecycle"]["retiredYears"] == []
    cls = c["pickClassLifecycle"]["classes"]["2026"]
    assert cls["status"] == "unknown"
    for key in boards["others"]:
        assert any(r.startswith(f"{key}:unknown") for r in cls["reasons"])
    assert len([n for n in _pick_rows(c) if n.startswith("2026")]) == 90


# ── served-league enumeration ─────────────────────────────────────────


def test_payload_evidence_must_belong_to_the_board_league(registry):
    raw = registry
    board_lid = _board_league_id(raw)
    block = dict(raw["sleeper"])
    block["draftClassEvidence"] = _retired_evidence(raw, 2026, "999999", "foreign")
    ev = dce.served_league_evidence(block)
    key = league_registry.league_key_for_sleeper_id(board_lid)
    assert ev[key] is None  # foreign evidence ignored, no snapshot → unknown

    # The snapshot is the fallback for the board league itself.
    snap = evidence_from_sleeper(
        league_key=key,
        sleeper_league_id=board_lid,
        drafts=[],
        picks_by_draft_id={},
        rostered_player_ids=[],
        observed_at=None,
    )
    dce.write_snapshot(snap)
    assert dce.served_league_evidence(block)[key] == snap


def test_a_league_without_a_scoring_card_is_consulted(registry):
    raw = registry
    ev = dce.served_league_evidence(raw["sleeper"])
    for cfg in _other_active_leagues(raw):
        assert cfg.key in ev and ev[cfg.key] is None


def test_evidence_collection_failure_is_none_and_partial_is_unobserved():
    assert dce.collect_league_draft_evidence("1", league_key="k", fetch=lambda url: None) is None

    def fetch(url):
        if url.endswith("/league/1/drafts"):
            return [{"draft_id": "d", "season": "2026", "status": "complete"}]
        return None  # league info, picks and rosters all fail

    ev = dce.collect_league_draft_evidence("1", league_key="k", fetch=fetch)
    assert ev is not None
    (d,) = ev.drafts
    assert d.pick_count is None and d.rostered_pick_count is None


def test_previous_league_drafts_are_followed_one_hop():
    def fetch(url):
        table = {
            "/league/2/drafts": [],
            "/league/2": {"previous_league_id": "1"},
            "/league/1/drafts": [{"draft_id": "old", "season": "2025", "status": "complete"}],
            "/draft/old/picks": [{"player_id": "a", "metadata": {"years_exp": "0"}}],
            "/league/2/rosters": [{"players": ["a"]}],
        }
        for suffix, value in table.items():
            if url.endswith(suffix):
                return value
        return None

    ev = dce.collect_league_draft_evidence("2", league_key="k", fetch=fetch)
    assert ev.draft_lists_observed == ("2", "1")
    (d,) = ev.drafts
    assert (d.season, d.pick_count, d.rostered_pick_count) == (2025, 1, 1)


def test_league_scoped_surfaces_use_their_own_league(registry):
    raw = registry
    board_lid = _board_league_id(raw)
    ev = dce.LeagueDraftEvidence.from_dict(_retired_evidence(raw, 2026, board_lid, "k"))
    dce.write_snapshot(ev)
    assert dce.active_seasons_for_league(board_lid, [2026, 2027, 2028]) == [2027, 2028]
    other = _other_active_leagues(raw)[0].sleeper_league_id
    assert dce.active_seasons_for_league(other, [2026, 2027]) == [2026, 2027]


def test_overlay_pick_ownership_drops_the_leagues_retired_class(registry):
    """The per-league ownership fold (Sleeper overlay) drops a class THIS
    league retired, keeps later ones, and keeps everything for a league with
    no evidence."""
    import datetime as _dt

    from src.api import sleeper_overlay

    raw = registry
    board_lid = _board_league_id(raw)
    this_year = _dt.datetime.now(_dt.timezone.utc).year
    dce.write_snapshot(
        dce.LeagueDraftEvidence.from_dict(
            _retired_evidence(raw, this_year, board_lid, "board_league")
        )
    )

    def seasons(league_id: str) -> set[int]:
        own = sleeper_overlay._build_pick_ownership(league_id, [1, 2], getter=lambda url: [])
        return {int(p["season"]) for plist in own.values() for p in plist}

    assert seasons(board_lid) == {this_year + 1, this_year + 2}
    assert seasons(OTHER_LEAGUE_ID) == {this_year, this_year + 1, this_year + 2}
