"""``league_intel.league_format.resolve_league_format`` — verified league format.

Composition only: sf1 + evidence state from ``league_registry``, the market
format and its ``tmf1`` fingerprint from ``trade.market_trade_format``.
Scoring snapshots are written to a temp dir (CI has no gitignored
``data/leagues``), never to the real store.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.api import league_registry as reg
from src.bdvm.actuals import nfl_projection_season
from src.league_intel import league_format as lf
from src.league_intel.league_format import (
    REQUIRED_FORMAT_AXES,
    STATE_UNKNOWN_LEAGUE,
    STATE_UNVERIFIED,
    STATE_VERIFIED,
    resolve_league_format,
)
from src.league_comparison.sleeper_scoring import scoring_fingerprint
from src.trade import market_trade_format as mtf

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = json.loads(
    (ROOT / "tests/fixtures/li_scoring/dynasty_main_league_2026.json").read_text("utf-8")
)
CARD = LEAGUE["scoring_settings"]
MAIN_ID = "1312006700437352448"
NEW_ID = "1320092771247222784"


@pytest.fixture(autouse=True)
def real_registry():
    """Point the registry at the TRACKED ``config/leagues/registry.json``.

    ``tests/conftest.py`` deliberately aims it at a nonexistent file for the
    session; capture and restore exactly (never assume unset is safe).
    """
    prior = os.environ.get("LEAGUE_REGISTRY_PATH")
    os.environ["LEAGUE_REGISTRY_PATH"] = str(ROOT / "config/leagues/registry.json")
    reg.reload_registry()
    yield
    if prior is None:
        os.environ.pop("LEAGUE_REGISTRY_PATH", None)
    else:
        os.environ["LEAGUE_REGISTRY_PATH"] = prior
    reg.reload_registry()


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    directory = tmp_path / "league-scoring"
    directory.mkdir()
    monkeypatch.setenv("LEAGUE_SCORING_SNAPSHOT_DIR", str(directory))
    reg._scoring_fp_cache.clear()
    yield directory
    reg._scoring_fp_cache.clear()


def _write_card(directory: Path, league_id: str, card, *, age_hours=0.0, season=None) -> Path:
    fetched = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    payload = {
        "sleeperLeagueId": league_id,
        "fetchedAt": fetched.isoformat(),
        "scoringSettings": dict(card),
        "season": str(nfl_projection_season() if season is None else season),
    }
    path = directory / f"scoring_{league_id}.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    reg._scoring_fp_cache.clear()
    return path


# ── no default league, ever ───────────────────────────────────────────────


def test_league_key_is_required_with_no_default():
    params = inspect.signature(resolve_league_format).parameters
    assert params["league_key"].default is inspect.Parameter.empty
    assert params["league_key"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            resolve_league_format(bad)  # type: ignore[arg-type]


def test_unknown_league_is_reported_not_defaulted(snapshot_dir):
    out = resolve_league_format("no_such_league")
    assert out.state == STATE_UNKNOWN_LEAGUE
    assert out.league_key == "no_such_league"
    assert out.scoring_fingerprint is None and out.format_fingerprint is None
    assert out.season is None
    assert out.unknown_axes == REQUIRED_FORMAT_AXES


# ── CI posture: no snapshot -> missing, nothing fingerprinted ─────────────


def test_without_a_scoring_snapshot_evidence_is_missing_and_nothing_is_proven(snapshot_dir):
    out = resolve_league_format("dynasty_main")
    assert out.scoring_evidence_state == "missing"
    assert out.scoring_fingerprint is None
    assert out.season is None
    assert out.market_format.scoring is None  # unknown, never {} or 0
    assert "scoring" in out.unknown_axes
    assert out.format_fingerprint is None
    assert out.state == STATE_UNVERIFIED
    assert out.reason.startswith("scoring_evidence_missing")
    # The known axes stay known, the unknown stays None (never 0 / False).
    fmt = out.market_format
    assert fmt.teams == 12 and fmt.roster_size == 58 and fmt.total_starters == 21
    assert fmt.best_ball is True and fmt.idp_enabled is True


def test_stale_card_proves_nothing(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD, age_hours=reg.SCORING_SNAPSHOT_MAX_AGE_HOURS + 1)
    out = resolve_league_format("dynasty_main")
    assert out.scoring_evidence_state == "stale"
    assert out.scoring_fingerprint is None and out.format_fingerprint is None
    assert out.season is None


def test_wrong_season_card_is_stale(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD, season=nfl_projection_season() - 1)
    out = resolve_league_format("dynasty_main")
    assert out.scoring_evidence_state == "stale" and out.season is None


# ── fresh card: verified, fingerprints from their owners ──────────────────


def test_fresh_card_verifies_the_format(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    out = resolve_league_format("dynasty_main")
    assert out.state == STATE_VERIFIED and out.reason is None
    assert out.scoring_evidence_state == "fresh"
    assert out.scoring_fingerprint == scoring_fingerprint(CARD)
    assert out.scoring_fingerprint.startswith("sf")
    assert out.season == nfl_projection_season()
    # tmf1 is exactly market_trade_format's own fingerprint of its own dict.
    expected = mtf.format_from_registry("dynasty_main").to_dict()["fingerprint"]
    assert out.format_fingerprint == expected
    assert out.format_fingerprint.startswith(mtf.FORMAT_FINGERPRINT_VERSION + ":")
    body = out.to_dict()
    assert body["formatFingerprint"] == out.format_fingerprint
    assert body["marketFormat"]["fingerprint"] == out.format_fingerprint


def test_numeric_form_and_absent_vs_zero_are_inherited_from_sf1(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    a = resolve_league_format("dynasty_main")
    # Every integral rate as an int (4.0 -> 4) and every explicit zero dropped.
    variant = {
        k: (int(v) if float(v).is_integer() else v) for k, v in CARD.items() if float(v) != 0.0
    }
    assert len(variant) < len(CARD)  # non-vacuous: the card does carry zeros
    assert any(isinstance(v, int) for v in variant.values())
    _write_card(snapshot_dir, MAIN_ID, variant)
    b = resolve_league_format("dynasty_main")
    assert a.scoring_fingerprint == b.scoring_fingerprint
    assert a.format_fingerprint == b.format_fingerprint


def test_key_order_does_not_change_either_fingerprint(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    a = resolve_league_format("dynasty_main")
    _write_card(snapshot_dir, MAIN_ID, dict(reversed(list(CARD.items()))))
    b = resolve_league_format("dynasty_main")
    assert (a.scoring_fingerprint, a.format_fingerprint) == (
        b.scoring_fingerprint,
        b.format_fingerprint,
    )


def test_a_scoring_change_changes_both_fingerprints(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    a = resolve_league_format("dynasty_main")
    changed = dict(CARD)
    changed["idp_sack"] = float(CARD["idp_sack"]) + 1.0
    _write_card(snapshot_dir, MAIN_ID, changed)
    b = resolve_league_format("dynasty_main")
    assert a.scoring_fingerprint != b.scoring_fingerprint
    assert a.format_fingerprint != b.format_fingerprint


def test_a_roster_shape_change_gives_a_different_tmf1(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    live = list(LEAGUE["roster_positions"])
    a = resolve_league_format("dynasty_main", roster_positions=live)
    one_less_te = list(live)
    one_less_te.remove("TE")
    b = resolve_league_format("dynasty_main", roster_positions=one_less_te)
    assert a.format_fingerprint and b.format_fingerprint
    assert a.format_fingerprint != b.format_fingerprint
    assert a.scoring_fingerprint == b.scoring_fingerprint  # scoring did not move


def test_live_host_lineup_matches_the_registry_lineup(snapshot_dir):
    """The captured live roster_positions and the registry starters describe
    the same format (the registry is not stale on lineup shape)."""
    _write_card(snapshot_dir, MAIN_ID, CARD)
    live = resolve_league_format("dynasty_main", roster_positions=LEAGUE["roster_positions"])
    registry = resolve_league_format("dynasty_main")
    assert live.market_format.vendor["starterSource"] == "sleeper_roster_positions"
    assert registry.market_format.vendor["starterSource"] == "registry_starters"
    assert live.format_fingerprint == registry.format_fingerprint
    assert live.market_format.teams == LEAGUE["settings"]["num_teams"]
    assert live.market_format.taxi_size == LEAGUE["settings"]["taxi_slots"]
    assert live.market_format.best_ball is bool(LEAGUE["settings"]["best_ball"])


def test_now_only_stamps_resolution_time(snapshot_dir):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    when = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    a = resolve_league_format("dynasty_main", now=when)
    b = resolve_league_format("dynasty_main")
    assert a.resolved_at == when.isoformat()
    assert (a.scoring_fingerprint, a.format_fingerprint, a.state) == (
        b.scoring_fingerprint,
        b.format_fingerprint,
        b.state,
    )


# ── dynasty_new is only ever resolved when named, from its own artifacts ──


def test_dynasty_new_resolves_its_own_format_without_touching_dynasty_main(
    snapshot_dir, monkeypatch
):
    _write_card(snapshot_dir, MAIN_ID, CARD)
    other = {"rec": 1.0, "pass_td": 4.0, "pass_yd": 0.04, "pass_int": -1.0}
    _write_card(snapshot_dir, NEW_ID, other)
    seen: list[str] = []
    real = reg.scoring_snapshot_path

    def spy(league_id):
        seen.append(str(league_id))
        return real(league_id)

    monkeypatch.setattr(reg, "scoring_snapshot_path", spy)
    reg._scoring_fp_cache.clear()
    out = resolve_league_format("dynasty_new")
    assert out.league_key == "dynasty_new"
    assert set(seen) == {NEW_ID}  # dynasty_main's artifact never read
    assert out.scoring_fingerprint == scoring_fingerprint(other)
    assert out.market_format.vendor["leagueKey"] == "dynasty_new"
    assert out.market_format.teams == 10
    main = resolve_league_format("dynasty_main")
    assert main.format_fingerprint != out.format_fingerprint


def test_dynasty_new_output_is_stable_with_dynasty_main_changes(snapshot_dir):
    _write_card(snapshot_dir, NEW_ID, {"rec": 1.0, "pass_td": 4.0})
    _write_card(snapshot_dir, MAIN_ID, CARD)
    before = resolve_league_format("dynasty_new").to_dict()
    changed = dict(CARD)
    changed["rec"] = 5.0
    _write_card(snapshot_dir, MAIN_ID, changed)
    after = resolve_league_format("dynasty_new").to_dict()
    before.pop("resolvedAt")
    after.pop("resolvedAt")
    assert before == after


# ── structure: one format hash; no production importer in batch 1 ─────────


def test_no_second_format_hash_is_defined_in_league_intel():
    for path in sorted((ROOT / "src/league_intel").glob("*.py")):
        text = path.read_text("utf-8")
        assert not re.search(r"""['"]tmf\d""", text), path
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name != "format_fingerprint", path
    src = (ROOT / "src/league_intel/league_format.py").read_text("utf-8")
    assert "hashlib" not in src and "sha1" not in src and "sha256" not in src
    assert lf.format_fingerprint is mtf.format_fingerprint


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


NEW_MODULES = ("src.league_intel.league_format", "src.nfl_data.synthetic_splits")


def test_no_production_surface_imports_the_new_modules_in_batch_1():
    surfaces = [ROOT / "server.py", *sorted((ROOT / "src/api").rglob("*.py"))]
    for path in surfaces:
        found = _imports(path)
        for mod in NEW_MODULES:
            assert not any(n == mod or n.startswith(mod + ".") for n in found), (path, mod)
        for pkg, name in (
            ("src.league_intel", "league_format"),
            ("src.nfl_data", "synthetic_splits"),
        ):
            assert f"{pkg}.{name}" not in found, path


def test_fresh_state_without_a_fingerprint_is_not_verified(snapshot_dir, monkeypatch):
    # The state and the fingerprint are separate registry reads; if the
    # snapshot expires between them the format must not read as verified.
    _write_card(snapshot_dir, MAIN_ID, CARD)
    monkeypatch.setattr(reg, "scoring_fingerprint_for_league", lambda cfg: None)
    out = resolve_league_format("dynasty_main")
    assert out.scoring_evidence_state == "fresh"
    assert out.scoring_fingerprint is None
    assert out.state == STATE_UNVERIFIED
    assert "scoring_fingerprint_unavailable" in out.reason
