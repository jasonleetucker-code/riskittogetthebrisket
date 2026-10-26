"""LI-5 replacement consolidation, phase P2 — the waiver population builder.

docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md §4.4 and
§8 items 4, 5 and 7; owner decisions D1 / D5 / D6 (2026-10-21).

The module is UNWIRED in this phase: the first test pins that nothing in
production imports it, which is what makes this phase behaviour-free.
Everything else is hermetic — synthetic contracts, a synthetic schedule and
synthetic host metadata; no network, no live board.
"""

from __future__ import annotations

import ast
import json
import pathlib
import random
import subprocess
import sys
from datetime import date

import pytest

from src.draft import displacement
from src.draft.rookie_pool import auction_rookie_keys
from src.draft.waiver_population import (
    HEALTH_APPLIED,
    HEALTH_EVIDENCE_UNAVAILABLE,
    HEALTH_EXCLUDING_REASONS,
    HEALTH_NOT_APPLICABLE,
    LENS_BANDED_NO_HEALTH,
    LENS_DYNASTY_SHADOW,
    LENS_THIS_SEASON,
    POPULATION_RULE,
    HealthEvidence,
    base_free_agent_rows,
    build_waiver_population,
    health_applicability,
    load_health_evidence,
)
from src.ros.availability import build_context

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "src" / "draft" / "waiver_population.py"

SEASON = 2026
LEAGUE = {"playoff_week_start": 15, "playoff_teams": 6}
# Week 7: KC plays Sunday 10/25, BUF is on bye.  Week 1 kicks off 9/10.
SCHEDULE = [
    {"game_type": "REG", "week": 1, "gameday": "2026-09-10", "home_team": "KC", "away_team": "BAL"},
    {
        "game_type": "REG",
        "week": 1,
        "gameday": "2026-09-13",
        "home_team": "BUF",
        "away_team": "NYJ",
    },
    {"game_type": "REG", "week": 7, "gameday": "2026-10-25", "home_team": "KC", "away_team": "NYJ"},
    {
        "game_type": "REG",
        "week": 7,
        "gameday": "2026-10-25",
        "home_team": "BAL",
        "away_team": "MIA",
    },
    {"game_type": "REG", "week": 8, "gameday": "2026-11-01", "home_team": "BUF", "away_team": "KC"},
    {
        "game_type": "REG",
        "week": 17,
        "gameday": "2027-01-03",
        "home_team": "KC",
        "away_team": "BUF",
    },
]


def ctx_for(leg, *, schedule=SCHEDULE, evidence=None, overrides=None, settings=None):
    league = dict(LEAGUE if settings is None else settings)
    if leg is not None:
        league["leg"] = leg
    return build_context(
        season=SEASON,
        league_settings=league,
        schedule_rows=schedule,
        evidence_payload=evidence,
        overrides=overrides or [],
    )


def prow(pid, pos, value, *, sources=3, rookie=False, name=None):
    return {
        "playerId": pid,
        "canonicalName": name or f"Player {pid}",
        "displayName": name or f"Player {pid}",
        "legacyRef": name or f"Player {pid}",
        "position": pos,
        "rankDerivedValue": value,
        "sourceCount": sources,
        "rookie": rookie,
    }


def contract_of(rows, teams=()):
    return {"playersArray": list(rows), "sleeper": {"teams": list(teams)}}


def meta(team="KC", status=None):
    return {"team": team, "injury_status": status}


def build(rows, *, rostered=(), unavailable=(), leg=7, meta_by_id=None, as_of=None, **kw):
    kw.setdefault("rookies_eligible", True)
    evidence = HealthEvidence(meta_by_id) if meta_by_id is not None else None
    return build_waiver_population(
        contract_of(rows),
        rostered,
        unavailable,
        availability=ctx_for(leg) if leg is not None else None,
        health_evidence=evidence,
        as_of=as_of or date(2026, 10, 21),
        **kw,
    )


def ids(rows):
    return [r["playerId"] for r in rows]


# ── phase boundary: unwired, lazy imports, one owner per concern ─────────


def _production_files():
    files = [p for root in ("src", "scripts") for p in (REPO / root).rglob("*.py")]
    return files + [REPO / "server.py"]


#: Phase P3 wired exactly these production modules (design §6 P3 row), each
#: behind ``waiver_population.enabled()``.  displacement imports only the
#: legacy free-agent selection (``base_free_agent_rows``) unconditionally —
#: that function IS the incumbent selection, folded here so it has one
#: definition.  Adding an importer is a new consumer and needs its own review.
P3_IMPORTERS = {
    "src/api/draft_optimizer_api.py",
    "src/draft/context.py",
    "src/draft/displacement.py",
    "src/roster_intel/droppability.py",
    "src/trade/roster_capacity.py",
}


def test_only_the_p3_consumers_import_the_population_builder():
    """P2 shipped unwired; P3 wires the design's consumers behind the
    default-OFF flag and nothing else (scripts are research tooling)."""
    importers = set()
    for path in _production_files():
        rel = path.relative_to(REPO).as_posix()
        # Any file under scripts/ (including subfolders such as
        # scripts/idp_accuracy/) is research tooling, per the docstring.
        if path == MODULE or rel.split("/", 1)[0] == "scripts":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.draft.waiver_population":
                importers.add(rel)
            elif isinstance(node, ast.ImportFrom) and (
                node.module in ("src.draft", "waiver_population", None) or node.level
            ):
                named = {a.name for a in node.names} | {node.module or ""}
                if "waiver_population" in named:
                    importers.add(rel)
            elif isinstance(node, ast.Import):
                if any(a.name == "src.draft.waiver_population" for a in node.names):
                    importers.add(rel)
    assert importers == P3_IMPORTERS


@pytest.mark.parametrize(
    "module,forbidden",
    [
        (
            "src.draft.waiver_population",
            [
                "src.trade.waiver",
                "src.trade.suggestions",
                "src.ros.availability",
                "src.ros.game_day_live",
                "src.draft.context",
                "src.draft.displacement",
                "src.league_intel.replacement",
            ],
        ),
        ("src.draft.displacement", ["src.trade.waiver", "src.trade.suggestions"]),
    ],
)
def test_import_boundary(module, forbidden):
    """Design §4.4 / §8 item 7: the draft layer reaches the trade and ros
    owners through function-level imports only, so displacement can import
    this module in P3 without a cycle.  Checked in a fresh interpreter."""
    code = (
        "import importlib, json, sys\n"
        f"importlib.import_module({module!r})\n"
        f"print(json.dumps([m for m in {forbidden!r} if m in sys.modules]))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_the_module_computes_no_level_and_no_private_health_rule():
    """Design §8 item 7.  The level belongs to LI-5 ``waiver_levels``; health
    belongs to ``availability.player_week_states``; add-pool eligibility to
    ``waiver_candidate_exclusion``.  This module may only compose them."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {
        n.func.id if isinstance(n.func, ast.Name) else n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }
    for banned in ("_banded_value", "fmean", "mean", "median", "waiver_levels", "sort"):
        assert banned not in called, banned
    assert {"player_week_states", "waiver_candidate_exclusion"} <= called
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert "statistics" not in imported
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    # Host fields are read only by the availability owner.
    assert "injury_status" not in strings
    assert "status" not in strings


# ── steps 1-2: the legacy free-agent set, per consumer (D6) ──────────────


def _fuzz_contract(rng):
    rows = []
    for i in range(rng.randint(0, 40)):
        r = prow(
            f"p{i}",
            rng.choice(["QB", "RB", "WR", "TE", "DL", "LB", "DB", "K", "DEF", "", " wr ", "PICK"]),
            rng.choice([None, 0, -5, 120, 900, 1500, 2400.5, "7"]),
        )
        if rng.random() < 0.1:
            r["assetClass"] = rng.choice(["pick", "PICK", "player"])
        if rng.random() < 0.1:
            r.pop("playerId")
        rows.append(r)
    if rng.random() < 0.1:
        rows.append("not a row")
    return {"playersArray": rows}


def test_base_rows_are_exactly_the_legacy_available_players():
    """The population before add-pool and health equals the free-agent set
    ``displacement._available_players`` builds today (design §8 item 4)."""
    for seed in range(300):
        rng = random.Random(seed)
        contract = _fuzz_contract(rng)
        rostered = {f"p{i}" for i in range(40) if rng.random() < 0.3}
        rostered |= {f"player p{i}" for i in range(40) if rng.random() < 0.1}
        unavailable = {f"P{i}" for i in range(40) if rng.random() < 0.1}
        legacy = displacement._available_players(contract, rostered, unavailable)
        got = base_free_agent_rows(contract, rostered, unavailable)
        assert [
            (float(r["rankDerivedValue"]), str(r["position"]).strip().upper()) for r in got
        ] == legacy, seed


def test_each_consumer_keeps_its_own_auction_rookie_population():
    """An unrostered top-72 rookie is the best DL: capacity (no exclusion)
    keeps him, Perfect Draft / droppability (auction rookies excluded) do
    not — the two populations stay distinct, as they are today (D6)."""
    rows = [
        prow("rk", "DL", 1918, rookie=True, name="Derrick Rookie"),
        prow("vet", "DL", 1700),
        prow("own", "DL", 2500),
    ]
    contract = contract_of(rows)
    rostered = {"own"}
    auction = auction_rookie_keys(contract)
    assert "rk" in auction

    capacity = build_waiver_population(contract, rostered, (), rookies_eligible=True)
    draft = build_waiver_population(contract, rostered, auction, rookies_eligible=True)
    assert ids(capacity.base_rows) == ["rk", "vet"]
    assert ids(draft.base_rows) == ["vet"]
    # Same answer the legacy anchor gives each consumer.
    assert displacement.waiver_values_by_position(contract, rostered, ()) == {"DL": 1918.0}
    assert displacement.waiver_values_by_position(contract, rostered, auction) == {"DL": 1700.0}
    assert draft.unavailable_keys_count == len(auction)


# ── step 3: add-pool eligibility (the waiver owner, as-is) ───────────────


def test_add_pool_gates_are_the_waiver_owners():
    rows = [
        prow("ok", "WR", 1800),
        prow("one-src", "WR", 2100, sources=1),
        prow("cheap", "WR", 400),
        prow("kick", "K", 900),
        prow("dst", "DEF", 900),
        prow("rook", "WR", 2000, rookie=True),
        prow("odd", "FB", 1500),
    ]
    pop = build(rows, leg=None, rookies_eligible=True)
    assert ids(pop.add_pool_rows) == ["ok", "kick", "dst", "rook"]
    assert pop.excluded_by_reason == {
        "single_source": 1,
        "below_min_value": 1,
        "position_not_offered": 1,
    }
    closed = build(rows, leg=None, rookies_eligible=False)
    assert ids(closed.add_pool_rows) == ["ok", "kick", "dst"]
    assert closed.excluded_by_reason["rookie_gate"] == 1


def test_rookie_window_is_injected_not_read_from_the_clock(monkeypatch):
    import src.trade.suggestions as suggestions
    import src.trade.waiver as waiver

    def _boom(*_a, **_k):
        raise AssertionError("the builder read the rookie window from the clock")

    # Both bindings: waiver.py holds its own reference from import time.
    monkeypatch.setattr(suggestions, "_rookies_eligible_today", _boom)
    monkeypatch.setattr(waiver, "_rookies_eligible_today", _boom)
    pop = build([prow("rook", "WR", 2000, rookie=True)], leg=None, rookies_eligible=False)
    assert pop.add_pool_rows == ()


# ── step 4: health, through the availability owner ───────────────────────


def test_health_applies_for_the_leagues_current_week():
    rows = [
        prow("healthy", "WR", 2000),
        prow("out", "WR", 2400),
        prow("ir", "WR", 2300),
        prow("q", "WR", 2200),
        prow("doubtful", "WR", 2100),
        prow("nometa", "WR", 1900),
    ]
    metas = {
        "healthy": meta(),
        "out": meta(status="Out"),
        "ir": meta(status="IR"),
        "q": meta(status="Questionable"),
        "doubtful": meta(status="Doubtful"),
    }
    pop = build(rows, meta_by_id=metas)
    assert ids(pop.rows) == ["healthy", "q", "doubtful"]
    assert ids(pop.add_pool_rows) == ids(pop.base_rows)  # lens B keeps everyone
    h = pop.health
    assert h["state"] == HEALTH_APPLIED and h["evaluationWeek"] == 7
    assert (h["available"], h["uncertain"], h["unavailableExcluded"], h["unknownExcluded"]) == (
        1,
        2,
        2,
        1,
    )
    assert h["excludedByHealthReason"] == {
        "host_designation_out": 1,
        "host_designation_ir": 1,
        "no_host_metadata": 1,
    }
    assert pop.health_by_id["nometa"] == ("unknown", "no_host_metadata")


def test_an_injury_flip_changes_the_population_deterministically():
    rows = [prow("a", "RB", 2000), prow("b", "RB", 1800)]
    before = build(rows, meta_by_id={"a": meta(), "b": meta()})
    after = build(rows, meta_by_id={"a": meta(status="Out"), "b": meta()})
    again = build(rows, meta_by_id={"a": meta(status="Out"), "b": meta()})
    assert ids(before.rows) == ["a", "b"]
    assert ids(after.rows) == ["b"]
    assert after == again


def test_a_bye_and_an_owner_override_do_not_remove_a_candidate():
    """Design F4c: the exclusion is an injury-reason allowlist."""
    rows = [prow("bye", "TE", 2000), prow("ovr", "TE", 1900), prow("ok", "TE", 1800)]
    overrides = [{"sleeperId": "ovr", "season": SEASON, "fromWeek": 7, "throughWeek": 7}]
    pop = build_waiver_population(
        contract_of(rows),
        (),
        rookies_eligible=True,
        availability=ctx_for(7, overrides=overrides),
        health_evidence=HealthEvidence({"bye": meta("BUF"), "ovr": meta(), "ok": meta()}),
        as_of=date(2026, 10, 21),
    )
    assert ids(pop.rows) == ["bye", "ovr", "ok"]
    assert pop.health["unavailableKept"] == {"bye": 1, "owner_override": 1}
    assert pop.health["unavailableExcluded"] == 0


def test_a_stated_return_after_this_weeks_game_excludes():
    rows = [prow("hurt", "LB", 2000), prow("ok", "LB", 1500)]
    evidence = {
        "asOf": "2026-10-20",
        "players": {"hurt": {"current": {"statusCode": "O", "returnDate": "2026-11-15"}}},
    }
    pop = build_waiver_population(
        contract_of(rows),
        (),
        rookies_eligible=True,
        availability=ctx_for(7, evidence=evidence),
        # news_updated before the ESPN report, so the return report stands.
        health_evidence=HealthEvidence(
            {"hurt": {**meta(status="IR"), "news_updated": 0}, "ok": meta()}
        ),
        as_of=date(2026, 10, 21),
    )
    assert ids(pop.rows) == ["ok"]
    assert pop.health["excludedByHealthReason"] == {"expected_return_after_game": 1}


def test_a_player_without_a_player_id_is_unknown_and_excluded():
    row = prow("x", "DB", 2000)
    row.pop("playerId")
    pop = build([row, prow("y", "DB", 1500)], meta_by_id={"y": meta()})
    assert ids(pop.rows) == ["y"]
    assert pop.health["excludedByHealthReason"] == {"no_player_id": 1}


def test_a_player_with_no_nfl_team_is_reported_available_today():
    """Design F3, documented rather than hidden: the existing owners do not
    check for an NFL team, so a teamless player passes.  Changing that is a
    separate owner decision (D5 iii), not something this builder invents."""
    pop = build([prow("ft", "LB", 2000)], meta_by_id={"ft": meta(team=None)})
    assert ids(pop.rows) == ["ft"]
    assert pop.health_by_id["ft"] == ("available", "host_reports_active")


def test_thin_and_empty_wires_are_populations_not_zeros():
    one = build([prow("only", "QB", 1600)], meta_by_id={"only": meta()})
    assert ids(one.rows) == ["only"]
    empty = build([prow("gone", "QB", 1600)], meta_by_id={"gone": meta(status="Out")})
    assert empty.rows == ()
    assert empty.provenance()["eligibleFreeAgents"] == 0
    none = build([], meta_by_id={})
    assert none.rows == () and none.base_rows == ()


# ── degradation: unknown is explicit, never healthy or zero (D5) ─────────


@pytest.mark.parametrize(
    "leg,settings,as_of,reason",
    [
        (None, None, date(2026, 8, 10), "no_current_week"),
        (0, None, date(2026, 8, 10), "no_current_week"),
        (1, None, date(2026, 8, 10), "before_season_kickoff"),
        (1, None, None, "season_start_unverified"),
        (17, {"playoff_week_start": 15, "playoff_teams": 6}, date(2027, 1, 2), None),
        (
            17,
            {"playoff_week_start": 15, "playoff_teams": 6},
            date(2027, 1, 10),
            "after_final_fantasy_week",
        ),
        (19, None, date(2027, 1, 20), "current_week_outside_league_season"),
    ],
)
def test_health_applicability(leg, settings, as_of, reason):
    ctx = ctx_for(leg, settings=settings)
    applicable, why = health_applicability(ctx, as_of=as_of)
    if reason is None:
        assert ctx.weeks[-1] == 17 and applicable is True
    else:
        assert (applicable, why) == (False, reason)


def test_week_one_after_kickoff_applies_and_the_final_week_after_its_game_does_not():
    assert health_applicability(ctx_for(1), as_of=date(2026, 9, 10)) == (True, None)
    final = ctx_for(17, settings={"playoff_week_start": 18})  # last week = 17
    assert final.weeks == (17,)
    assert health_applicability(final, as_of=date(2027, 1, 3)) == (True, None)
    assert health_applicability(final, as_of=date(2027, 1, 4)) == (
        False,
        "after_final_fantasy_week",
    )


def test_a_calendar_fallback_week_is_not_the_leagues_week():
    ctx = build_context(
        season=SEASON, league_settings=LEAGUE, schedule_rows=SCHEDULE, fallback_current_week=7
    )
    assert ctx.current_week == 7
    assert health_applicability(ctx, as_of=date(2026, 10, 21)) == (
        False,
        "current_week_not_from_league",
    )
    assert health_applicability(None, as_of=None) == (False, "no_availability_context")


def test_off_season_population_stops_after_the_add_pool_and_says_so():
    rows = [prow("out", "WR", 2400), prow("ok", "WR", 2000)]
    metas = {"out": meta(status="Out"), "ok": meta()}
    pop = build(rows, leg=1, as_of=date(2026, 8, 10), meta_by_id=metas)
    assert ids(pop.rows) == ["out", "ok"]  # an Out player is NOT treated as healthy...
    assert pop.health == {  # ...the stamp says health was not applied, and why
        "state": HEALTH_NOT_APPLICABLE,
        "reason": "before_season_kickoff",
        "asOf": None,
    }
    assert pop.health_by_id == {}


@pytest.mark.parametrize(
    "evidence,reason",
    [
        (None, "no_health_evidence"),
        (
            HealthEvidence(None, None, "players_db_missing_stale_or_incomplete"),
            "players_db_missing_stale_or_incomplete",
        ),
    ],
)
def test_missing_health_evidence_is_labelled_not_silent(evidence, reason):
    rows = [prow("out", "WR", 2400), prow("ok", "WR", 2000)]
    pop = build_waiver_population(
        contract_of(rows),
        (),
        rookies_eligible=True,
        availability=ctx_for(7),
        health_evidence=evidence,
        as_of=date(2026, 10, 21),
    )
    assert ids(pop.rows) == ids(pop.add_pool_rows) == ["out", "ok"]
    assert pop.health["state"] == HEALTH_EVIDENCE_UNAVAILABLE
    assert pop.health["reason"] == reason


def _write_players_db(path, fetched_at, players):
    path.write_text(json.dumps({"fetchedAt": fetched_at, "players": players}), encoding="utf-8")


def _forbid_network(monkeypatch):
    import socket
    import urllib.request

    def _boom(*_a, **_k):
        raise AssertionError("health evidence touched the network")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


def test_load_health_evidence_is_disk_only_and_fails_closed(tmp_path, monkeypatch):
    import src.ros.game_day_live as gdl

    _forbid_network(monkeypatch)
    db = tmp_path / "players.json"
    monkeypatch.setattr(gdl, "_players_db_path", lambda: db)
    monkeypatch.setattr(gdl, "_players_db_cache", {})
    now = 1_800_000_000.0
    fresh = "2027-01-15T07:59:00+00:00"  # one minute before ``now``

    # Missing file.
    ev = load_health_evidence({"a"}, now=now)
    assert ev.players_meta is None and ev.reason == "players_db_missing_stale_or_incomplete"

    # Fresh and complete.
    _write_players_db(db, fresh, {"a": meta(), "b": meta(status="Out")})
    ev = load_health_evidence({"a", "b"}, now=now)
    assert set(ev.players_meta) == {"a", "b"} and ev.reason is None and ev.as_of is None

    # Lacking a requested id.
    ev = load_health_evidence({"a", "zzz"}, now=now)
    assert ev.players_meta is None

    # Stale (> 24 h).
    _write_players_db(db, "2027-01-13T00:00:00+00:00", {"a": meta()})
    monkeypatch.setattr(gdl, "_players_db_cache", {})
    ev = load_health_evidence({"a"}, now=now)
    assert ev.players_meta is None


# ── lenses, provenance, purity ───────────────────────────────────────────


def test_lens_a_is_served_lens_b_is_a_named_shadow():
    rows = [prow("out", "DB", 2400), prow("ok", "DB", 2000)]
    pop = build(rows, meta_by_id={"out": meta(status="Out"), "ok": meta()})
    assert pop.served_lens == LENS_THIS_SEASON
    assert ids(pop.rows_for_lens(LENS_THIS_SEASON)) == ["ok"]
    with pytest.raises(LookupError):
        pop.rows_for_lens(LENS_BANDED_NO_HEALTH)
    assert ids(pop.rows_for_lens(LENS_DYNASTY_SHADOW)) == ["out", "ok"]
    with pytest.raises(ValueError):
        pop.rows_for_lens("best_unrostered")
    prov = pop.provenance()
    assert prov["rule"] == POPULATION_RULE
    assert prov["lens"] == LENS_THIS_SEASON
    assert (prov["baseFreeAgents"], prov["addPoolEligible"], prov["eligibleFreeAgents"]) == (
        2,
        2,
        1,
    )


def test_the_builder_does_not_mutate_its_inputs():
    rows = [prow("a", "WR", 2000), prow("b", "WR", 1500, sources=1)]
    contract = contract_of(rows)
    snapshot = json.dumps(contract, sort_keys=True)
    metas = {"a": meta(), "b": meta()}
    meta_snapshot = json.dumps(metas, sort_keys=True)
    build_waiver_population(
        contract,
        ["zzz"],
        rookies_eligible=True,
        availability=ctx_for(7),
        health_evidence=HealthEvidence(metas),
        as_of=date(2026, 10, 21),
    )
    assert json.dumps(contract, sort_keys=True) == snapshot
    assert json.dumps(metas, sort_keys=True) == meta_snapshot


@pytest.mark.parametrize(
    "leg,meta_by_id",
    [(None, {"out": {"team": "KC", "injury_status": "Out"}}), (7, None)],
    ids=["not_applicable", "evidence_unavailable"],
)
def test_a_health_free_population_never_carries_lens_a(leg, meta_by_id):
    """Design F4: when health did not run, the served rows are the banded,
    health-free population under their own label, never lens A's."""
    pop = build([prow("out", "DB", 2400), prow("ok", "DB", 2000)], leg=leg, meta_by_id=meta_by_id)
    assert pop.served_lens == LENS_BANDED_NO_HEALTH
    assert pop.provenance()["lens"] == LENS_BANDED_NO_HEALTH
    assert ids(pop.rows_for_lens(LENS_BANDED_NO_HEALTH)) == ["out", "ok"]
    with pytest.raises(LookupError):
        pop.rows_for_lens(LENS_THIS_SEASON)


def test_the_excluding_reasons_are_exactly_the_owners_out_codes():
    """F4c: an enumerated allowlist.  If the availability owner gains or
    loses an OUT-type code, this fails and the change is reviewed here."""
    from src.ros import availability as av

    host_out = {f"host_designation_{c.lower()}" for c in av._HOST_OUT}
    assert HEALTH_EXCLUDING_REASONS == host_out | {
        "expected_return_after_game",
        "expected_return_after_season",
    }


@pytest.mark.parametrize("code", ["Out", "IR", "PUP", "NA", "Sus", "DNR", "COV"])
def test_every_current_week_out_designation_excludes(code):
    rows = [prow("x", "LB", 2000), prow("ok", "LB", 1500)]
    pop = build(rows, meta_by_id={"x": meta(status=code), "ok": meta()})
    assert ids(pop.rows) == ["ok"], code


def test_an_unreviewed_unavailable_reason_keeps_the_player_and_is_reported(monkeypatch):
    import src.ros.availability as av

    real = av.player_week_states

    def fake(pid, meta_, ctx):
        out = real(pid, meta_, ctx)
        if pid == "x":
            out = {wk: av.WeekState(av.UNAVAILABLE, "host_designation_newcode") for wk in out}
        return out

    monkeypatch.setattr(av, "player_week_states", fake)
    pop = build([prow("x", "LB", 2000)], meta_by_id={"x": meta()})
    assert ids(pop.rows) == ["x"]
    assert pop.health["unavailableKept"] == {"host_designation_newcode": 1}


def test_a_context_without_a_recorded_week_source_is_not_applicable():
    from dataclasses import replace

    ctx = replace(ctx_for(7), basis={})
    assert health_applicability(ctx, as_of=date(2026, 10, 21)) == (
        False,
        "current_week_not_from_league",
    )


def test_the_health_loader_is_asked_once_for_exactly_the_add_pool_ids():
    calls = []

    def loader(player_ids):
        calls.append(list(player_ids))
        return HealthEvidence({"a": meta(), "c": meta(status="Out")})

    rows = [prow("a", "WR", 2000), prow("b", "WR", 2100, sources=1), prow("c", "WR", 1900)]
    pop = build_waiver_population(
        contract_of(rows),
        (),
        rookies_eligible=True,
        availability=ctx_for(7),
        health_loader=loader,
        as_of=date(2026, 10, 21),
    )
    assert calls == [["a", "c"]]  # "b" is single-source: not in the add pool
    assert ids(pop.rows) == ["a"]

    calls.clear()
    off = build_waiver_population(
        contract_of(rows),
        (),
        rookies_eligible=True,
        availability=ctx_for(None),
        health_loader=loader,
    )
    assert calls == [] and off.health["state"] == HEALTH_NOT_APPLICABLE


def test_load_health_evidence_strips_ids(tmp_path, monkeypatch):
    import src.ros.game_day_live as gdl

    _forbid_network(monkeypatch)
    db = tmp_path / "players.json"
    monkeypatch.setattr(gdl, "_players_db_path", lambda: db)
    monkeypatch.setattr(gdl, "_players_db_cache", {})
    _write_players_db(db, "2027-01-15T07:59:00+00:00", {"a": meta()})
    ev = load_health_evidence([" a "], now=1_800_000_000.0)
    assert ev.players_meta is not None
